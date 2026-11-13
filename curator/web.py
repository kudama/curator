"""Loopback-only app server. No external frontend dependencies."""
import argparse
import base64
import json
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .service import Service
from .store import Store
from .tools import image_bytes
from .tools import handbrake_presets


class App(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        self.service = service
        self.session = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


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

    def allowed(self, mutate=False):
        port = self.server.server_port
        if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
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
            origin = self.headers.get('Origin')
            if origin not in {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}:
                return False
        return True

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
            return self.reply({'error': 'Invalid host'}, 403)
        path = urlsplit(self.path).path
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'application/javascript'),
                  '/style.css': ('style.css', 'text/css'), '/workbench.js': ('workbench.js', 'application/javascript'), '/collections.js': ('collections.js', 'application/javascript')}
        if path in static:
            name, kind = static[path]
            return self.reply((Path(__file__).parent / 'static' / name).read_bytes(), content_type=kind, cookie=path == '/')
        if not self.allowed():
            return self.reply({'error': 'Open Curator in this browser first'}, 403)
        try:
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
                service.start(data['library'])
                result = {'started': True}
            elif path == '/api/task/edit':
                result = service.edit_task(data['id'], data['plan'], data['version'])
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
            elif path == '/api/task/review':
                result = service.review(data['id'], data['version'], 'manual comparison', background=True)
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
        except (ValueError, KeyError, TypeError) as e:
            self.reply({'error': str(e) if isinstance(e, ValueError) else 'Missing or invalid request field'}, 400)
        except Exception:
            self.reply({'error': 'Operation failed; configuration or provider needs attention'}, 500)


def main():
    parser = argparse.ArgumentParser(description='Curator local Plex library workspace')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--state', default='~/Library/Application Support/Curator')
    parser.add_argument('--open', action='store_true', help='Open the local app in your default browser')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    try:
        store = Store(args.state)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Curator could not open its local state: {error}\n')
    try:
        server = App(('127.0.0.1', args.port), Service(store))
    except OSError as error:
        store.close()
        parser.exit(2, f'Curator could not listen on 127.0.0.1:{args.port}: {error}. Close the other instance or try --port 8791.\n')
    print(f'Curator: http://127.0.0.1:{server.server_port}', flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == '__main__':
    main()
