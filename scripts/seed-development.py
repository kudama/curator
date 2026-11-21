#!/usr/bin/env python3
"""Create a small synthetic catalogue in a fresh DEV/TEST sandbox only."""

import argparse
from contextlib import closing
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from curator import development, tools
from curator.service import Service
from curator.store import Store, now
from curator.rules import stable_id


def seed(sandbox):
    sandbox = Path(sandbox).expanduser().resolve()
    state = sandbox / 'state'
    development.configure(sandbox, state)
    with closing(Store(state)) as store:
        if store.all('libraries') or store.all('assets') or store.all('tasks'):
            raise ValueError('Development catalogue already contains data; preserving it')
        media = sandbox / 'media'
        art = sandbox / 'artwork'
        exports = sandbox / 'exports'
        for folder in (media, art, exports):
            development.check_path(folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        ffmpeg = tools.executable({}, 'ffmpeg')
        library = dict(id='development:home', server='development', key='home', title='DEV · Sample home movies',
                       type='movie', agent='com.plexapp.agents.none', profile='home',
                       mappings=[dict(plex_root='/synthetic', local_root=str(media))], themes=['Family', 'Pets'])
        records = []
        for number, (title, color) in enumerate([('Park afternoon', 'steelblue'), ('Pet adventures', 'seagreen'), ('Family picnic', 'coral')], 1):
            path = media / f'sample-{number}.mp4'
            image = art / f'sample-{number}.png'
            if path.exists() or image.exists():
                raise ValueError('Synthetic output already exists; preserving it')
            subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'lavfi', '-i',
                            f'color=c={color}:s=640x360:r=12', '-t', '12', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
            subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-i', str(path), '-frames:v', '1', str(image)], check=True)
            aid = stable_id('development', number)
            item = dict(ratingKey=str(number), type='movie', title=title, summary='Synthetic DEV/TEST sample. No personal media.',
                        thumb='/synthetic/cover', art='/synthetic/background', Media=[{'Part': [{'file': '/synthetic/' + path.name}]}])
            records.append(dict(id=aid, library=library['id'], title=title, rating_key=str(number),
                                plex_path='/synthetic/' + path.name, local_path=str(path), fingerprint=tools.fingerprint(path),
                                technical=tools.probe(path, {}), item=item, present=True, scanned=now(),
                                development_artwork={'cover': str(image), 'background': str(image)}))
        service = Service(store)
        with store.transaction():
            store.put('settings', 'config', dict(archive_root=str(exports), artwork_archive_path=str(art)))
            store.put('libraries', library['id'], library)
            for asset in records:
                store.put('assets', asset['id'], asset)
                service.task(asset, dict(kind='metadata', reason='Review synthetic sample metadata'))
            for kind in ['upscale', 'optimize', 'home', 'metadata', 'mage_generation', 'file_operations', 'rename', 'join', 'group']:
                store.put('settings', service.pause_key(None, kind), True)
        print('Created 3 synthetic media items; all queues paused; no provider credentials configured.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development-root', required=True)
    args = parser.parse_args()
    seed(args.development_root)
