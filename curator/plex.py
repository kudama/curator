"""Small replaceable Plex adapter. No direct Plex database access."""
import json
import re
import hashlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler


class PlexError(ValueError):
    pass


class NoPlexRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise PlexError('Plex redirects are not allowed; configure the direct server URL')


class NoImageRedirect(NoPlexRedirect):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise PlexError('Plex image redirects are not allowed')


class Plex:
    ARTWORK = {
        'cover': ('posters', 'poster', 'thumb', 'coverPoster'),
        'background': ('arts', 'art', 'art', 'background'),
        'logo': ('clearLogos', 'clearLogo', 'clearLogo', 'clearLogo'),
        'square': ('squareArts', 'squareArt', 'squareArt', 'backgroundSquare'),
    }

    @staticmethod
    def artwork_path(item, kind):
        if kind not in Plex.ARTWORK:
            raise ValueError('Unknown artwork kind')
        _, _, field, image_type = Plex.ARTWORK[kind]
        return item.get(field) or next((row.get('url') for row in item.get('Image', [])
                                       if row.get('type') == image_type), None)

    def __init__(self, url, token, transport=None):
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise PlexError('Plex URL must be an HTTP(S) server root without credentials')
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise PlexError('Plex token is required')
        self.url, self.token = url.rstrip('/'), token
        self.transport = transport or build_opener(NoPlexRedirect()).open
        self.image_transport = transport or build_opener(NoImageRedirect()).open

    def request(self, path, method='GET', params=None, data=None, content_type=None, ignore_body=False):
        if not path.startswith('/') or path.startswith('//') or '?' in path:
            raise PlexError('Invalid Plex API path')
        query = '?' + urlencode(params, doseq=True) if params else ''
        headers = {'X-Plex-Token': self.token, 'Accept': 'application/json',
                   'X-Plex-Product': 'Curator', 'X-Plex-Client-Identifier': 'curator-local'}
        if content_type:
            headers['Content-Type'] = content_type
        try:
            with self.transport(Request(self.url + path + query, data=data, headers=headers, method=method), timeout=20) as r:
                raw = r.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise PlexError('Plex response is too large')
            if ignore_body:
                return {}
            return json.loads(raw).get('MediaContainer', {}) if raw else {}
        except HTTPError as error:
            code = error.code
            error.close()
            raise PlexError(f'Plex returned HTTP {code}') from None
        except PlexError:
            raise
        except (URLError, TimeoutError, OSError, ValueError):
            raise PlexError('Plex request failed; check server, token and connectivity') from None

    def libraries(self):
        server = self.request('/identity').get('machineIdentifier')
        if not server:
            raise PlexError('Plex server did not return an identity')
        return [dict(id=f"{server}:{x['key']}", server=server, key=str(x['key']),
                     title=x['title'], type=x['type'], agent=x.get('agent'), locations=x.get('Location', []))
                for x in self.request('/library/sections').get('Directory', [])
                if x.get('type') in {'movie', 'show'}]

    def items(self, library):
        start, seen = 0, set()
        while True:
            block = self.request('/library/sections/' + quote(library['key'], safe='') + '/all',
                                 params={'type': 4 if library['type'] == 'show' else 1,
                                         'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 200})
            rows = block.get('Metadata', [])
            if not rows:
                return
            fresh = [x for x in rows if str(x['ratingKey']) not in seen]
            if not fresh:
                raise PlexError('Plex pagination did not advance')
            for item in fresh:
                seen.add(str(item['ratingKey']))
                yield item
            start += len(rows)
            if start >= int(block.get('totalSize', start)):
                return

    def item(self, key):
        rows = self.request('/library/metadata/' + quote(str(key), safe='')).get('Metadata', [])
        if len(rows) != 1:
            raise PlexError('Plex item is missing or ambiguous')
        return rows[0]

    @staticmethod
    def validate_changes(changes):
        allowed = {'title', 'summary', 'studio', 'tagline', 'genre', 'collection', 'label', 'cast'}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise PlexError('Unsupported metadata fields')
        for field, value in changes.items():
            if field == 'cast':
                from .cast import validate_rows
                validate_rows(value)
                if any(set(row) - {'name', 'role', 'thumb'} for row in value):
                    raise PlexError('Cast profiles and uploads must use the cast save workflow')
            elif field in {'genre', 'collection', 'label'}:
                if not isinstance(value, list) or len(value) > 200 or not all(isinstance(x, str) and x.strip() and len(x) <= 500 for x in value):
                    raise PlexError('Tags and labels must be lists of nonempty names')
            elif not isinstance(value, str) or len(value) > 50000:
                raise PlexError('Metadata fields must be text')

    def edit(self, library, item, changes):
        self.validate_changes(changes)
        params = {'id': item['ratingKey'], 'type': 4 if item['type'] == 'episode' else 1}
        for field, value in changes.items():
            if field == 'cast':
                removed = [row['tag'] for row in item.get('Role', []) if row['tag'] not in {x['name'] for x in value}]
                if removed:
                    params['actor[].tag.tag-'] = ','.join(quote(x, safe='') for x in removed)
                for index, row in enumerate(value):
                    prefix = f'actor[{index}]'
                    params[prefix + '.tag.tag'] = row['name']
                    # Live Plex stores the character/role on the credit (tagging), not the person tag.
                    # actor[index] positions determine cast order.
                    params[prefix + '.tagging.text'] = row.get('role', '')
                    params[prefix + '.tag.thumb'] = row.get('thumb', '')
                    params[prefix + '.locked'] = 1
                    existing = next((x for x in item.get('Role', []) if x.get('tag') == row['name']), {})
                    if existing.get('tagKey'):
                        params[prefix + '.tag.tagKey'] = existing['tagKey']
                params['actor.locked'] = 1
                continue
            elif field in {'genre', 'collection', 'label'}:
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise PlexError('Tags must be a list of strings')
                # Explicit removal is needed for omitted tags and clearing a list.
                existing = [x['tag'] for x in item.get(field.title(), [])]
                removed = [x for x in existing if x not in value]
                if removed:
                    params[field + '[].tag.tag-'] = ','.join(quote(x, safe='') for x in removed)
                for index, tag in enumerate(value):
                    params[f'{field}[{index}].tag.tag'] = tag
            else:
                if not isinstance(value, str):
                    raise PlexError('Metadata must be text')
                params[field + '.value'] = value
            params[field + '.locked'] = 1
        self.request('/library/sections/' + quote(library['key'], safe='') + '/all', 'PUT', params)
        return self.item(item['ratingKey'])

    def artwork(self, key, image, kind='cover'):
        if kind not in self.ARTWORK:
            raise ValueError('Unknown artwork kind')
        base = '/library/metadata/' + quote(str(key), safe='')
        plural, singular, _, _ = self.ARTWORK[kind]
        endpoint = base + '/' + plural
        before = {x.get('ratingKey') for x in self.request(endpoint).get('Metadata', [])}
        self.request(endpoint, 'POST', data=image,
                     content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg', ignore_body=True)
        after = self.request(endpoint).get('Metadata', [])
        uploaded = [x for x in after if x.get('ratingKey') not in before and
                    str(x.get('ratingKey', '')).startswith('upload://')]
        if len(uploaded) != 1:
            raise PlexError('Upload was sent, but Plex did not identify one new image. Inspect artwork in Plex before retrying.')
        candidate = uploaded[0]['ratingKey']
        # Uploading and selecting are distinct Plex operations.
        field = singular
        self.request(base + '/' + field, 'PUT', params={'url': candidate}, ignore_body=True)
        selected = [x for x in self.request(endpoint).get('Metadata', [])
                    if x.get('ratingKey') == candidate and x.get('selected') in (True, 1, '1')]
        if len(selected) != 1:
            raise PlexError('Image uploaded, but Plex did not confirm its selection. Inspect artwork in Plex.')
        result = self.item(key)
        if not self.artwork_path(result, kind):
            raise PlexError('Plex selected the image but did not return its artwork field')
        return result

    def image(self, key, kind):
        if kind not in self.ARTWORK:
            raise ValueError('Unknown artwork kind')
        item = self.item(key)
        path = self.artwork_path(item, kind)
        if not isinstance(path, str) or not path.startswith('/library/metadata/') or '..' in path.split('/') or '?' in path or '#' in path:
            raise PlexError('No current artwork is available')
        try:
            with self.transport(Request(self.url + path, headers={'X-Plex-Token': self.token, 'Accept': 'image/*'}), timeout=20) as response:
                image = response.read(10 * 1024 * 1024 + 1)
            if len(image) > 10 * 1024 * 1024 or not (image.startswith(b'\xff\xd8\xff') or image.startswith(b'\x89PNG\r\n\x1a\n')):
                raise PlexError('Current artwork is not a supported JPEG/PNG')
            return image
        except (HTTPError, URLError, TimeoutError, OSError):
            raise PlexError('Current artwork could not be loaded from Plex') from None

    def binary_image(self, path, params=None):
        # Only contact the configured Plex server. Never attach the token to an actor's external URL.
        query = '?' + urlencode(params) if params else ''
        try:
            with self.image_transport(Request(self.url + path + query, headers={'X-Plex-Token': self.token,
                                                                         'Accept': 'image/*'}), timeout=20) as response:
                data = response.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')):
                raise PlexError('Plex did not return a JPEG/PNG cast picture')
            return data
        except (HTTPError, URLError, TimeoutError, OSError):
            raise PlexError('Plex could not load the cast picture') from None

    def cast_image(self, thumb):
        if not isinstance(thumb, str) or not thumb or len(thumb) > 4000:
            raise PlexError('No cast picture is available')
        parsed = urlsplit(thumb)
        if parsed.username or parsed.password or parsed.fragment or '\n' in thumb or '\r' in thumb:
            raise PlexError('Invalid cast picture reference')
        if not ((not parsed.scheme and not parsed.netloc and re.fullmatch(r'/library/metadata/[0-9]+/(?:file|thumb(?:/[0-9]+)?)', parsed.path))
                or (parsed.scheme in {'http', 'https'} and parsed.hostname)):
            raise PlexError('Invalid cast picture reference')
        return self.binary_image('/photo/:/transcode', {'url': thumb, 'width': 300, 'height': 300, 'minSize': 1})

    def cast_photo(self, key, image):
        # Keep an unselected image in this item's bundle. Each title owns its copy,
        # so removing another title cannot break a reused person's picture.
        base = '/library/metadata/' + quote(str(key), safe='')
        endpoint = base + '/posters'
        before = self.request(endpoint).get('Metadata', [])
        selected_before = [x.get('ratingKey') for x in before if x.get('selected') in (True, 1, '1')]
        if len(selected_before) != 1:
            raise PlexError('Select a cover in Plex before adding cast pictures')
        self.request(endpoint, 'POST', data=image,
                     content_type='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg', ignore_body=True)
        after = self.request(endpoint).get('Metadata', [])
        candidates = [x.get('ratingKey') for x in after if x.get('ratingKey') not in {r.get('ratingKey') for r in before}
                      and re.fullmatch(r'upload://posters/[a-fA-F0-9]+', str(x.get('ratingKey', '')))]
        selected_after = [x.get('ratingKey') for x in after if x.get('selected') in (True, 1, '1')]
        if selected_after != selected_before:
            if len(selected_after) != 1 or selected_after[0] not in candidates:
                raise PlexError('The Plex cover changed during cast upload; inspect it before retrying')
            self.request(base + '/poster', 'PUT', params={'url': selected_before[0]}, ignore_body=True)
            restored = self.request(endpoint).get('Metadata', [])
            if [x.get('ratingKey') for x in restored if x.get('selected') in (True, 1, '1')] != selected_before:
                raise PlexError('Plex changed the cover during cast upload; inspect the cover before retrying')
        if len(candidates) != 1:
            raise PlexError('Plex did not identify one new cast picture; inspect before retrying')
        candidate = candidates[0]
        data = self.binary_image(base + '/file', {'url': candidate})
        if hashlib.sha256(data).digest() != hashlib.sha256(image).digest():
            raise PlexError('Plex cast picture bytes differ from the upload')
        thumb = base + '/file?' + urlencode({'url': candidate})
        self.cast_image(thumb)
        return thumb

    def poster(self, key, image):
        return self.artwork(key, image, 'cover')

    def refresh(self, key):
        self.request('/library/metadata/' + quote(str(key), safe='') + '/refresh', 'PUT')

    def playlist(self, server, title, keys):
        rows = self.request('/playlists', params={'playlistType': 'video'}).get('Metadata', [])
        existing = [x for x in rows if x.get('title') == title]
        if existing:
            if len(existing) != 1 or existing[0].get('smart'):
                raise PlexError('Playlist title is ambiguous or belongs to a smart playlist')
            observed = self.request('/playlists/' + quote(str(existing[0]['ratingKey']), safe='') + '/items').get('Metadata', [])
            if [str(x['ratingKey']) for x in observed] == keys:
                return {'verified': True, 'rating_key': str(existing[0]['ratingKey']), 'unchanged': True}
            raise PlexError('A different playlist already uses this title; choose a new title to preserve it')
        uri = 'server://' + server + '/com.plexapp.plugins.library/library/metadata/' + ','.join(keys)
        made = self.request('/playlists', 'POST', {'title': title, 'type': 'video', 'smart': 0, 'uri': uri}).get('Metadata', [])
        if len(made) != 1:
            raise PlexError('Playlist creation receipt is uncertain; inspect Plex before retry')
        key = str(made[0]['ratingKey'])
        observed = self.request('/playlists/' + quote(key, safe='') + '/items').get('Metadata', [])
        if [str(x['ratingKey']) for x in observed] != keys:
            raise PlexError('Playlist order readback differs; inspect Plex before retry')
        return {'verified': True, 'rating_key': key}

    def automatic_trash(self):
        rows = self.request('/:/prefs').get('Setting', [])
        value = next((x.get('value') for x in rows if x.get('id') == 'autoEmptyTrash'), None)
        if str(value).lower() not in {'0', 'false'}:
            raise PlexError('Turn off Plex “Empty trash automatically after every scan” before renaming files')
        return False

    def scan_folder(self, library, folder):
        self.request('/library/sections/' + quote(library['key'], safe='') + '/refresh',
                     params={'path':str(folder)}, ignore_body=True)

    def collections(self, library):
        """List the complete selected-library collection catalog, without mutations."""
        start, seen, rows = 0, set(), []
        while True:
            payload=self.request('/library/sections/'+quote(str(library['key']),safe='')+'/collections',
                params={'X-Plex-Container-Start':start,'X-Plex-Container-Size':200})
            page=payload.get('Metadata',[])
            total=int(payload['totalSize']) if 'totalSize' in payload else None
            if not page:
                if total is not None and start<total:raise PlexError('Collection list is incomplete; refresh and try again')
                break
            fresh=0
            for item in page:
                identity=str(item.get('ratingKey',''));title=item.get('title')
                if not identity or not isinstance(title,str) or not title.strip():raise PlexError('Plex returned an invalid collection')
                if identity in seen:continue
                seen.add(identity);fresh+=1
                rows.append(dict(key=identity,title=title,smart=str(item.get('smart',0)).lower() in {'1','true'},count=item.get('childCount')))
            if not fresh:raise PlexError('Collection pagination did not advance')
            start+=len(page)
            if total is not None and start>=total or total is None and len(page)<200:break
        return sorted(rows,key=lambda row:(row['title'].casefold(),row['key']))

    def metadata_choices(self, library, field):
        """Read library-scoped categories; selecting a name never writes metadata."""
        if field == 'collection':
            return self.collections(library)
        if field not in {'genre', 'label'}:
            raise PlexError('Unsupported metadata choice field')
        start, seen, rows = 0, set(), []
        while True:
            payload = self.request('/library/sections/' + quote(str(library['key']), safe='') + '/' + field,
                params={'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 200})
            page = payload.get('Directory', [])
            total = int(payload['totalSize']) if 'totalSize' in payload else None
            if not page:
                if total is not None and start < total:
                    raise PlexError('Category list is incomplete; refresh and try again')
                break
            fresh = 0
            for item in page:
                title = item.get('title')
                if not isinstance(title, str) or not title.strip():
                    raise PlexError('Plex returned an invalid category')
                identity = str(item.get('key', title))
                if identity in seen:
                    continue
                seen.add(identity)
                fresh += 1
                rows.append(dict(key=identity, title=title, smart=False))
            if not fresh:
                raise PlexError('Category pagination did not advance')
            start += len(page)
            if total is not None and start >= total or total is None and len(page) < 200:
                break
        return sorted(rows, key=lambda row: (row['title'].casefold(), row['key']))

    def group_state(self, library, kind, title, owned=None):
        """Read one non-smart collection/playlist; never adopt by title alone."""
        if kind not in {'collection', 'playlist'}:
            raise PlexError('Unknown grouping type')
        path = '/playlists' if kind == 'playlist' else '/library/sections/' + quote(library['key'],safe='') + '/collections'
        payload = self.request(path, params={'X-Plex-Container-Size':1000})
        rows = payload.get('Metadata', [])
        if int(payload.get('totalSize', len(rows))) > len(rows):
            raise PlexError('Grouping list is incomplete; narrow the library before applying')
        matches = [x for x in rows if x.get('title','').casefold() == title.casefold()]
        if not matches:
            if owned:
                raise PlexError('Managed grouping was removed; inspect Plex before retrying')
            return None
        if len(matches) != 1 or matches[0].get('smart') or not owned or str(matches[0]['ratingKey']) != owned['key']:
            raise PlexError('This title belongs to an unmanaged or ambiguous grouping; choose another title')
        key = str(matches[0]['ratingKey'])
        base = '/playlists/'+quote(key,safe='') if kind=='playlist' else '/library/metadata/'+quote(key,safe='')
        payload = self.request(base + ('/items' if kind=='playlist' else '/children'), params={'X-Plex-Container-Size':1000})
        rows = payload.get('Metadata', [])
        if int(payload.get('totalSize',len(rows))) > len(rows):
            raise PlexError('Grouping membership is incomplete')
        keys = [str(x['ratingKey']) for x in rows]
        same = keys == owned['keys'] if kind=='playlist' else set(keys) == set(owned['keys'])
        if not same:
            raise PlexError('Grouping changed outside Curator; inspect before replacing membership')
        return dict(key=key, rows=rows, keys=keys, base=base)

    def managed_group(self, library, kind, title, keys, owned, receipt):
        state = self.group_state(library, kind, title, owned)
        uri = 'server://' + library['server'] + '/com.plexapp.plugins.library/library/metadata/' + ','.join(keys)
        if state is None:
            params = {'title':title,'smart':0,'uri':uri}
            if kind=='playlist':
                params['type']='video';endpoint='/playlists'
            else:
                params.update(type=1,sectionId=library['key']);endpoint='/library/collections'
            made = self.request(endpoint,'POST',params).get('Metadata',[])
            if len(made)!=1:
                raise PlexError('Creation outcome uncertain; inspect Plex before retrying')
            key = str(made[0]['ratingKey'])
            receipt(dict(kind=kind,key=key,keys=keys,uncertain=True))
            base = '/playlists/'+quote(key,safe='') if kind=='playlist' else '/library/metadata/'+quote(key,safe='')
        else:
            key,base = state['key'],state['base']
            if kind=='playlist' and state['keys']!=keys:
                for row in state['rows']:
                    self.request(base+'/items/'+quote(str(row['playlistItemID']),safe=''),'DELETE',ignore_body=True)
                self.request(base+'/items','PUT',{'uri':uri},ignore_body=True)
            elif kind=='collection' and set(state['keys'])!=set(keys):
                for removed in set(state['keys'])-set(keys):
                    self.request(base+'/items/'+quote(removed,safe=''),'DELETE',ignore_body=True)
                added=[k for k in keys if k not in state['keys']]
                if added:
                    add_uri='server://'+library['server']+'/com.plexapp.plugins.library/library/metadata/'+','.join(added)
                    self.request(base+'/items','PUT',{'uri':add_uri},ignore_body=True)
        result = dict(kind=kind,key=key,keys=keys)
        self.group_state(library,kind,title,result)
        receipt(result)
        return result
