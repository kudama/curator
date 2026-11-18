"""Local app server with explicit private-network opt-in; no frontend dependencies."""
import argparse
import base64
import json
import ipaddress
import re
import secrets
import threading
from contextlib import nullcontext
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .service import Service
from .store import Store
from .tools import image_bytes
from .tools import handbrake_presets
from .runtime import ServiceRuntime, RestartBlocked, Restarting, RESTART_EXIT_CODE


def listener_settings(host, expected_hosts=()):
    if not isinstance(host, str):
        raise ValueError('Bind host must be an explicit IPv4 address')
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        raise ValueError('Bind host must be an explicit loopback or RFC1918 IPv4 address') from None
    private = any(address in ipaddress.IPv4Network(network)
                  for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if not address.is_loopback and not private:
        raise ValueError('Bind host must be loopback or RFC1918 IPv4; wildcard/public binds are refused')
    if not isinstance(expected_hosts, (tuple, list)):
        raise ValueError('Expected hostnames must be a list or tuple')
    aliases = []
    for name in expected_hosts:
        if (not isinstance(name, str) or len(name) > 253 or not name
                or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                       for label in name.split('.'))):
            raise ValueError('Expected hostnames must be bare DNS names without scheme, port or path')
        aliases.append(name.lower())
    return str(address), tuple(aliases)


class App(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, expected_hosts=(), managed_service=False):
        host, expected_hosts = listener_settings(address[0], expected_hosts)
        self.service = service
        self.runtime = ServiceRuntime(service, managed=managed_service)
        self.session = secrets.token_urlsafe(32)
        super().__init__((host, address[1]), Handler)
        self.allowed_authorities = {name + ':' + str(self.server_port) for name in expected_hosts}
        self.allowed_authorities.add(host + ':' + str(self.server_port))
        if host == '127.0.0.1':
            self.allowed_authorities.add('localhost:' + str(self.server_port))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No private media names, paths or credentials in HTTP logs.

    def reply(self, data, status=200, content_type='application/json', cookie=False, download=None):
        raw = json.dumps(data, allow_nan=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', 'curator_session=' + self.server.session + '; HttpOnly; SameSite=Strict; Path=/')
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="' + download + '"')
        self.end_headers()
        self.wfile.write(raw)

    def request_host(self):
        hosts = self.headers.get_all('Host', [])
        return hosts[0] if len(hosts) == 1 and hosts[0] in self.server.allowed_authorities else None

    def allowed(self, mutate=False):
        host = self.request_host()
        if host is None:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            return False
        session = cookie.get('curator_session')
        if not session or not secrets.compare_digest(session.value, self.server.session):
            return False
        if mutate:
            if self.headers.get('X-Curator-Request') != '1':
                return False
            if self.headers.get_all('Origin', []) != ['http://' + host]:
                return False
        return True

    def dispatch(self, method, mutate=False):
        runtime = getattr(self.server, 'runtime', None)
        try:
            with runtime.request(mutate) if runtime else nullcontext():
                return method()
        except Restarting:
            return self.reply({'error':'Curator is restarting; reconnect shortly.'},503)

    def do_GET(self):
        return self.dispatch(self.get_response)

    def get_response(self):
        if self.request_host() is None:
            return self.reply({'error': 'Invalid host'}, 403)
        path = urlsplit(self.path).path
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'application/javascript'),
                  '/style.css': ('style.css', 'text/css'), '/workbench.js': ('workbench.js', 'application/javascript'), '/queue-board.js': ('queue-board.js', 'application/javascript'), '/collections.js': ('collections.js', 'application/javascript')}
        if path in static:
            name, kind = static[path]
            return self.reply((Path(__file__).parent / 'static' / name).read_bytes(), content_type=kind, cookie=path == '/')
        if not self.allowed():
            return self.reply({'error': 'Open Curator in this browser first'}, 403)
        try:
            if path == '/api/service/status':
                return self.reply(self.server.runtime.status())
            if path == '/api/review-session':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.review_session(query['id'][0]))
            if path == '/api/library/metadata-choices':
                query = parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.library_metadata_choices(query['library'][0], query['field'][0]))
            if path == '/api/assets/image':
                query=parse_qs(urlsplit(self.path).query)
                image=self.server.service.asset_thumbnail(query['asset'][0])
                return self.reply(image,content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg')
            if path == '/api/folders/read':
                query = parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.folder_read(query['id'][0]))
            if path == '/api/folders/image':
                query = parse_qs(urlsplit(self.path).query)
                image = self.server.service.folder_image(query['photo'][0])
                return self.reply(image, content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg')
            if path == '/api/state':
                return self.reply(self.server.service.state())
            if path == '/api/artwork/image':
                query = parse_qs(urlsplit(self.path).query)
                image = self.server.service.artwork_image(query['id'][0], query['kind'][0])
                return self.reply(image, content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg')
            if path == '/api/metadata/read':
                query = parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.read_metadata(query['id'][0]))
            if path == '/api/cast/profiles':
                return self.reply({'profiles': self.server.service.cast_profiles()})
            if path == '/api/cast/image':
                query = parse_qs(urlsplit(self.path).query)
                if query.get('profile'):
                    image = self.server.service.cast_profile_image(query['profile'][0])
                else:
                    image = self.server.service.cast_item_image(query['id'][0], int(query['index'][0]))
                return self.reply(image, content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg')
            if path == '/api/task/publication-log':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.publication_log(query['id'][0]))
            if path == '/api/review-batch':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.review_batch(query['id'][0]))
            if path == '/api/review-batches':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply({'batches':self.server.service.review_batches(None if query.get('scope')==['all'] else query['library'][0])})
            if path == '/api/cleanup':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.cleanup_receipt(query['id'][0]))
            if path == '/api/files/suggestions':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.file_suggestions(query['asset'][0]))
            if path == '/api/files/sample':
                query=parse_qs(urlsplit(self.path).query)
                return self.reply(self.server.service.join_sample(query['id'][0],query['name'][0]),content_type='image/jpeg')
            if path == '/api/handbrake/presets':
                try:
                    return self.reply(handbrake_presets(self.server.service.config()))
                except ValueError as error:
                    return self.reply({'available': False, 'presets': [], 'error': str(error)})
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'frames']:
                asset, name = parts[2:]
                if len(asset) != 24 or not all(c in '0123456789abcdef' for c in asset) or name not in {'0.jpg', '1.jpg', '2.jpg', '3.jpg'}:
                    raise ValueError('Unknown frame')
                target = self.server.service.store.root / 'frames' / asset / name
                return self.reply(image_bytes(target), content_type='image/jpeg')
            if path in {'/api/branding', '/api/branding/logo'}:
                query = parse_qs(urlsplit(self.path).query)
                if path.endswith('/logo'):
                    target = self.server.service.branding_logo(query['id'][0], query['folder'][0])
                    return self.reply(image_bytes(target), content_type='image/png' if target.suffix == '.png' else 'image/jpeg')
                return self.reply(self.server.service.folder_branding(query['id'][0]))
            if path == '/api/kometa':
                query = parse_qs(urlsplit(self.path).query)
                if query.get('mode') == ['mcu']:
                    library = self.server.service.library(query['library'][0])
                    names = [x['title'] for x in self.server.service.store.all('libraries')
                             if x['server'] == library['server'] and x['profile'] == 'commercial']
                    variables = {('use_' + key): False for key in
                                 ['arrow', 'dcau', 'dragonball', 'pokemon', 'startrek', 'starwars', 'clonewars', 'xmen']}
                    variables.update(libraries=', '.join(names), use_mcu=True)
                    config = {'playlist_files': [{'default': 'playlist', 'template_variables': {
                        **variables}}]}
                    return self.reply(json.dumps(config, indent=2).encode(), content_type='application/yaml', download='curator-mcu.yml')
                config = self.server.service.kometa(query['library'][0], query['title'][0], query.get('asset', []))
                return self.reply(json.dumps(config, indent=2).encode(), content_type='application/yaml', download='curator-collections.yml')
            if len(parts) == 5 and parts[:2] == ['api', 'comparison']:
                key, side, name = parts[2:]
                if len(key) != 24 or not all(c in '0123456789abcdef' for c in key) or side not in {'source', 'output'} or name not in {'0.jpg', '1.jpg', '2.jpg', '3.jpg'}:
                    raise ValueError('Unknown comparison')
                target = self.server.service.store.root / 'comparisons' / key / side / name
                return self.reply(image_bytes(target), content_type='image/jpeg')
            return self.reply({'error': 'Not found'}, 404)
        except (ValueError, OSError, KeyError) as e:
            return self.reply({'error': str(e) if isinstance(e, ValueError) else 'Resource unavailable'}, 400)

    def do_POST(self):
        return self.dispatch(self.post_response, mutate=True)

    def post_response(self):
        if not self.allowed(mutate=True):
            return self.reply({'error': 'Local session/origin required'}, 403)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size <= 0 or size > 16 * 1024 * 1024:
                raise ValueError('Request must be between 1 byte and 16 MiB')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            service = self.server.service
            path = urlsplit(self.path).path
            if path == '/api/service/restart':
                if data:
                    raise ValueError('Restart accepts no parameters')
                result = self.server.runtime.request_restart()
                try:
                    self.reply(result,202)
                finally:
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path == '/api/folders/defaults':
                result=service.save_folder_defaults(data['id'], data['settings'], data.get('revision'), data.get('branding_revision'))
            elif path == '/api/folders/preview':
                result=service.folder_preview(data['id'], data['settings'])
            elif path == '/api/folders/queue':
                result=service.queue_folder_preview(data['preview'])
            elif path == '/api/files/plan':
                result=service.file_plan(data)
            elif path == '/api/library/locations':
                result=service.refresh_library_locations(data['library'])
            elif path == '/api/library/presence':
                result=service.sync_presence(data['library'])
            elif path == '/api/files/comparison':
                result=service.join_comparison(data['id'])
            elif path == '/api/config':
                service.save_config(data)
                result = {'saved': True}
            elif path == '/api/connect':
                result = service.connect()
            elif path == '/api/library':
                service.save_library(data['id'], data['settings'])
                result = {'saved': True}
            elif path == '/api/scan':
                service.scan(data['library'])
                result = {'started': True}
            elif path == '/api/run':
                result=service.start(None if data.get('scope')=='all' else data['library'],data.get('kind'))
            elif path == '/api/queue/pause':
                result=service.pause_queues(None if data.get('scope')=='all' else data['library'],data.get('kind'))
            elif path == '/api/queue/limits':
                result=service.set_queue_limits(data['limits'])
            elif path == '/api/processing-defaults':
                result=service.save_processing_defaults(data['library'],data['kind'],data['values'])
            elif path == '/api/run/readiness':
                result=service.run_readiness(None if data.get('scope')=='all' else data['library'])
            elif path == '/api/recovery/retry-failed':
                result=service.retry_failed_results(data['tasks'])
            elif path == '/api/task/edit':
                result = service.edit_task(data['id'], data['plan'], data['version'])
            elif path == '/api/artwork/candidates':
                result = service.artwork_candidates(data['id'],data['version'],data['count'])
            elif path == '/api/mage/quote':
                result = service.mage_quote(data['tasks'])
            elif path == '/api/mage/authorize':
                result = service.authorize_mage(data['quote'],data.get('consent'))
            elif path == '/api/mage/resume':
                result = service.resume_mage(data['id'],data['version'])
            elif path == '/api/cast/profile/create':
                if set(data)-{'name','image'}:raise ValueError('Invalid new person fields')
                result = service.create_cast_profile(data['name'],data.get('image'))
            elif path == '/api/portrait/remember':
                result = service.remember_portrait_identity(data['asset'],data['index'])
            elif path == '/api/portrait/save':
                result = service.save_portrait(data['profile_id'], data['revision'], data['image'])
            elif path == '/api/portrait/plan':
                result = service.portrait_plan(data['profile_id'], data['revision'], data['targets'])
            elif path == '/api/artwork/plan':
                result = service.artwork_plan(data['assets'], data['kind'], data['preset_id'], data.get('overrides'), data.get('images'), data.get('originals'), data.get('references'))
            elif path == '/api/artwork/save-style':
                result = service.save_artwork_style(data['id'], data['name'])
            elif path == '/api/mage/key':
                from .mage import Mage
                Mage(service.store.root).save_key(data['key'])
                result = {'configured': Mage(service.store.root).configured()}
            elif path == '/api/mage/check':
                from .mage import Mage
                result = Mage(service.store.root).discover()
            elif path == '/api/metadata/task':
                result = service.metadata_task(data['asset'])
            elif path == '/api/metadata/queue':
                result = service.queue_metadata(data['id'], data['version'], data['changes'])
            elif path == '/api/metadata/apply':
                result = service.apply_metadata(data['id'], data['version'], data['changes'])
            elif path == '/api/cast/apply':
                result = service.apply_cast(data['id'], data['version'], data['cast'])
            elif path == '/api/task/action':
                result = service.action(data['id'], data['action'], data['version'], data.get('handbrake_preset'))
            elif path == '/api/queue/change':
                result=service.change_queue(None if data.get('scope')=='all' else data['library'],data['expected'],order=data.get('order'),remove=data.get('remove'))
            elif path == '/api/file-queue/order':
                if set(data)!={'expected','order'}:raise ValueError('File ordering requires the full waiting snapshot and order')
                result=service.change_file_queue_order(data['expected'],data['order'])
            elif path == '/api/task/review':
                result = service.review(data['id'], data['version'], 'manual comparison', background=True)
            elif path == '/api/review-batch/prepare':
                result=service.prepare_review_batch(None if data.get('scope')=='all' else data['library'],data['tasks'])
            elif path == '/api/review-session/open':
                result=service.open_review_session(data.get('id'),data.get('library'),data.get('kind'),data.get('tasks'))
            elif path == '/api/review-session/step':
                result=service.step_review_session(data['id'],data['version'],data['task'],data['decision'])
            elif path == '/api/review-batch/accept-selected':
                result=service.accept_selected_results(None if data.get('scope')=='all' else data['library'],data['tasks'],data['count'],data['confirmation'])
            elif path == '/api/review-batch/reject-selected':
                result=service.reject_selected_results(None if data.get('scope')=='all' else data['library'],data['tasks'],data['count'])
            elif path == '/api/review-batch/publish':
                result=service.publish_review_batch(data['id'],data['count'])
            elif path == '/api/review-batch/stop':
                result=service.stop_review_batch(data['id'])
            elif path == '/api/cleanup/preview':
                result=service.cleanup_preview(data['library'])
            elif path == '/api/cleanup/delete':
                result=service.delete_backups(data['id'],data['tasks'],data['count'],data['confirmation'])
            elif path == '/api/cleanup/restore':
                result=service.restore_cleanup_backup(data['id'])
            elif path == '/api/comparison':
                result = service.comparison(data['id'])
            elif path == '/api/playlist/preview':
                result = service.playlist_plan(data['library'], data['title'], data['main_show'],
                                               data['companion_show'], data.get('offset', 0))
            elif path == '/api/cover/prompt':
                result = {'prompt': service.cover_prompt(data['id'], data['title'])}
            elif path == '/api/branding/choice':
                logo = base64.b64decode(data['logo'], validate=True) if data.get('logo') else None
                result = service.save_branding_choice(data['id'], data['choice'], logo)
            elif path == '/api/branding/save':
                logo = base64.b64decode(data['logo'], validate=True) if data.get('logo') else None
                result = service.save_branding(data['id'], data['folder'], data['template'], data.get('revision'), logo)
            elif path == '/api/branding/confirm':
                result = service.confirm_branding(data['id'], data.get('folder'), data.get('revision'), data.get('use', True))
            elif path == '/api/cover/apply':
                image = base64.b64decode(data['image'], validate=True)
                if len(image) > 10 * 1024 * 1024 or not (image.startswith(b'\xff\xd8\xff') or image.startswith(b'\x89PNG\r\n\x1a\n')):
                    raise ValueError('Invalid JPEG/PNG artwork')
                result = service.apply_cover(data['id'], image, data.get('kind', 'cover'))
            else:
                return self.reply({'error': 'Not found'}, 404)
            self.reply(result)
        except RestartBlocked as error:
            self.reply({'error':str(error)},409)
        except (ValueError, KeyError, TypeError) as e:
            self.reply({'error': str(e) if isinstance(e, ValueError) else 'Missing or invalid request field'}, 400)
        except Exception:
            self.reply({'error': 'Operation failed; configuration or provider needs attention'}, 500)


def main():
    parser = argparse.ArgumentParser(description='Curator local Plex library workspace')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--host', default='127.0.0.1', help='Explicit loopback or RFC1918 IPv4 bind address')
    parser.add_argument('--expected-host', action='append', default=[],
                        help='Additional bare browser hostname, such as foundry; repeat as needed')
    parser.add_argument('--state', default='~/Library/Application Support/Curator')
    parser.add_argument('--open', action='store_true', help='Open the local app in your default browser')
    parser.add_argument('--managed-service', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    try:
        host, expected_hosts = listener_settings(args.host, args.expected_host)
    except ValueError as error:
        parser.error(str(error))
    try:
        store = Store(args.state)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Curator could not open its local state: {error}\n')
    try:
        server = App((host, args.port), Service(store), expected_hosts=expected_hosts,
                     managed_service=args.managed_service)
    except OSError as error:
        store.close()
        parser.exit(2, f'Curator could not listen on {host}:{args.port}: {error}. Close the other instance or try --port 8791.\n')
    print(f'Curator: http://{host}:{server.server_port}', flush=True)
    from .build import RUNNING_BUILD
    print('Curator version '+RUNNING_BUILD['version']+' | build '+RUNNING_BUILD['revision']+
          (' (modified checkout)' if RUNNING_BUILD['dirty'] else '')+
          ' | started '+RUNNING_BUILD['started_at'], flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://{host}:{server.server_port}')
    restart = False
    try:
        while True:
            server.serve_forever()
            if not server.runtime.restart_requested:
                break
            if server.runtime.wait_for_idle():
                restart = True
                break
            server.runtime.cancel_restart()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    if restart:
        raise SystemExit(RESTART_EXIT_CODE)


if __name__ == '__main__':
    main()
