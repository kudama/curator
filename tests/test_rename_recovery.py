"""#154: review rename receipts and restore retained artwork and cast pictures.

Fake Plex only: synthetic files in a temporary folder and temporary state.
"""

import copy
import hashlib
import unittest
from unittest.mock import patch

from curator.errors import UserError
from curator.plex import PlexError
import test_rename_preservation
from test_rename_preservation import JPEG, PNG

UPLOADED = '/library/metadata/1/file?url=upload%3A%2F%2Fposters%2Faa'
PERSON = b'\x89PNG\r\n\x1a\n' + b'curated portrait'
AGENT_PERSON = b'\xff\xd8\xff' + b'agent portrait'
AGENT_POSTER = b'\xff\xd8\xff' + b'agent default poster'


class Recovery(unittest.TestCase):
    # Reuse the preservation harness without re-running its tests.
    plan = test_rename_preservation.Preservation.plan
    run_task = test_rename_preservation.Preservation.run_task
    tearDown = test_rename_preservation.Preservation.tearDown
    scan = test_rename_preservation.Preservation.scan
    receipts = test_rename_preservation.Preservation.receipts
    rename_and_rematch = test_rename_preservation.Preservation.rename_and_rematch

    def setUp(self):
        test_rename_preservation.Preservation.setUp(self)
        plex = self.plex
        row = plex.rows['1']
        row['Role'] = [
            {'tag': 'Person', 'role': 'Self', 'thumb': UPLOADED},
            {'tag': 'Guest', 'role': 'Host', 'thumb': 'https://agent.example/guest.jpg'},
            {'tag': 'Friend', 'role': '', 'thumb': ''},
        ]
        plex.pictures = {UPLOADED: PERSON, 'https://agent.example/guest.jpg': AGENT_PERSON}
        plex.uploads = []

        def cast_image(thumb):
            if thumb not in plex.pictures:
                raise PlexError('Plex could not load the cast picture')
            return plex.pictures[thumb]

        def cast_photo(key, image):
            thumb = f'/library/metadata/{key}/file?url=upload%3A%2F%2Fposters%2F{hashlib.sha256(image).hexdigest()[:8]}'
            plex.pictures[thumb] = image
            plex.uploads.append(('cast', key))
            return thumb

        def artwork(key, image, kind):
            plex.images[str(key), kind] = image
            plex.uploads.append((kind, key))
            plex.rows[str(key)]['thumb' if kind == 'cover' else 'art'] = f'/library/metadata/{key}/{kind}/new'
            return copy.deepcopy(plex.rows[str(key)])

        plex.cast_image, plex.cast_photo, plex.artwork = cast_image, cast_photo, artwork
        with self.store.transaction():
            asset = self.store.get('assets', self.assets[0]['id'])
            asset['item'] = copy.deepcopy(row)
            self.store.put('assets', asset['id'], asset)

    def lost_after_rematch(self):
        """Plex rematched the renamed file: description, poster and the uploaded portrait were replaced."""
        agent_role = [
            {'tag': 'Person', 'role': 'Self', 'thumb': 'https://agent.example/person.jpg'},
            {'tag': 'Guest', 'role': 'Host', 'thumb': 'https://agent.example/guest.jpg'},
            {'tag': 'Friend', 'role': '', 'thumb': ''},
        ]
        self.plex.pictures['https://agent.example/person.jpg'] = AGENT_PERSON
        task, receipt = self.rename_and_rematch(summary='', Role=agent_role, images={'cover': AGENT_POSTER})
        return receipt, self.service.rename_receipt_view(receipt['receipt'])

    def snapshot(self):
        return (
            copy.deepcopy(self.store.where('settings', record_type='rename_receipt')),
            sorted(t['id'] for t in self.store.all('tasks')),
            len(self.store.curator_history()),
        )

    def test_capture_keeps_uploaded_pictures_and_references_agent_pictures(self):
        self.run_task(self.plan())
        [receipt] = self.receipts()
        people = {p['name']: p for p in receipt['portraits']}
        self.assertEqual(people['Person']['state'], 'retained')
        self.assertEqual(people['Person']['sha256'], hashlib.sha256(PERSON).hexdigest())
        self.assertEqual(self.service.retained_rename_portrait(receipt, 0), PERSON)
        folder = self.store.root / 'rename-receipts' / receipt['receipt']
        self.assertEqual((folder / people['Person']['file']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(people['Guest']['state'], 'reference')
        self.assertEqual(people['Friend']['state'], 'none')

    def test_an_unreadable_picture_is_recorded_and_never_blocks_the_rename(self):
        del self.plex.pictures[UPLOADED]
        task = self.run_task(self.plan())
        self.assertEqual(task['status'], 'applied')
        [receipt] = self.receipts()
        self.assertEqual(receipt['portraits'][0]['state'], 'unavailable')

    def test_viewing_a_receipt_shows_differences_and_never_writes(self):
        receipt, _ = self.lost_after_rematch()
        before = self.snapshot()
        view = self.service.rename_receipt_view(receipt['receipt'])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(view['status'], 'review')
        self.assertTrue(view['rematched'])
        self.assertEqual(view['renamed']['after'], receipt['destination_plex_path'].rsplit('/', 1)[1])
        summary = next(m for m in view['metadata'] if m['field'] == 'summary')
        self.assertEqual((summary['captured'], summary['current'], summary['state']), ('Description', '', 'differs'))
        self.assertEqual(view['metadata_restore']['state'], 'proposed')
        cover = next(a for a in view['artwork'] if a['kind'] == 'cover')
        self.assertEqual((cover['state'], cover['verified'], cover['can_restore']), ('changed', True, True))
        background = next(a for a in view['artwork'] if a['kind'] == 'background')
        self.assertEqual((background['state'], background['can_restore']), ('retained', False))
        person = next(p for p in view['portraits'] if p['name'] == 'Person')
        self.assertEqual((person['state'], person['can_restore']), ('changed', True))
        self.assertNotIn('can_restore', next(p for p in view['portraits'] if p['name'] == 'Guest'))
        self.assertEqual(self.service.rename_receipt_image(receipt['receipt'], kind='cover'), PNG)
        self.assertEqual(self.service.rename_receipt_image(receipt['receipt'], person=0), PERSON)
        self.assertEqual(self.plex.uploads, [])
        listed = self.service.rename_receipts(self.library['id'])
        self.assertEqual((listed[0]['id'], listed[0]['needs_review']), (receipt['receipt'], 3))

    def test_artwork_restore_is_a_review_task_and_publishes_only_after_review(self):
        receipt, view = self.lost_after_rematch()
        result = self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])
        [task_id] = result['tasks']
        task = self.service.get_task(task_id)
        self.assertEqual((task['kind'], task['status']), ('artwork', 'awaiting_review'))
        self.assertEqual(task['plan']['candidate'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(task['plan']['original'], hashlib.sha256(AGENT_POSTER).hexdigest())
        self.assertEqual(task['plan']['rating_key'], '100')
        self.assertEqual(self.plex.uploads, [])  # Nothing is written until the operator reviews it.
        self.assertEqual(self.plex.images['100', 'cover'], AGENT_POSTER)
        cover = next(a for a in result['receipt']['artwork'] if a['kind'] == 'cover')
        self.assertEqual((cover['restore']['state'], cover['can_restore']), ('waiting_for_review', False))
        with self.assertRaisesRegex(UserError, 'already open'):
            self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])
        self.service.review(task_id, task['version'], 'explicit fixture approval')
        self.assertEqual(self.plex.images['100', 'cover'], PNG)
        self.assertEqual(self.service.get_task(task_id)['status'], 'applied')
        cover = next(a for a in self.service.rename_receipt_view(view['id'])['artwork'] if a['kind'] == 'cover')
        self.assertEqual(cover['restore']['state'], 'restored')

    def test_artwork_changed_in_plex_before_review_is_a_conflict_not_an_overwrite(self):
        receipt, view = self.lost_after_rematch()
        [task_id] = self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])['tasks']
        self.plex.images['100', 'cover'] = JPEG  # Someone chose a different poster in Plex meanwhile.
        try:
            self.service.review(task_id, 1, 'explicit fixture approval')
        except UserError:
            pass
        self.assertEqual(self.plex.images['100', 'cover'], JPEG)
        task = self.service.get_task(task_id)
        self.assertNotEqual(task['status'], 'applied')
        self.assertIn('changed after preview', task['error'])
        cover = next(a for a in self.service.rename_receipt_view(view['id'])['artwork'] if a['kind'] == 'cover')
        self.assertEqual(cover['restore']['state'], 'needs_attention')
        self.assertEqual(self.service.retained_rename_artwork(receipt, 'cover'), PNG)  # Still retained.

    def test_restores_refuse_stale_views_changed_files_tampered_and_missing_receipts(self):
        receipt, view = self.lost_after_rematch()
        with self.assertRaisesRegex(UserError, 'changed since you opened'):
            self.service.restore_rename_artwork(view['id'], 'old-version', ['cover'])
        with self.assertRaisesRegex(UserError, 'missing'):
            self.service.restore_rename_artwork('0' * 24, view['version'], ['cover'])
        with self.assertRaisesRegex(UserError, 'Unknown'):
            self.service.rename_receipt_view('../../etc')
        folder = self.store.root / 'rename-receipts' / receipt['receipt']
        cover = folder / receipt['artwork']['cover']['file']
        cover.write_bytes(b'\x89PNG\r\n\x1a\n' + b'tampered')
        self.assertFalse(
            next(a for a in self.service.rename_receipt_view(view['id'])['artwork'] if a['kind'] == 'cover')[
                'can_restore'
            ]
        )
        with self.assertRaisesRegex(UserError, 'changed on disk'):
            self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])
        cover.unlink()
        with self.assertRaisesRegex(UserError, 'missing from the receipt'):
            self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])
        (self.folder / receipt['destination_plex_path'].rsplit('/', 1)[1]).write_bytes(b'replaced file')
        with self.assertRaisesRegex(UserError, 'changed or moved'):
            self.service.restore_rename_portraits(view['id'], view['version'], [0], view['cast_digest'])
        self.assertEqual([t for t in self.store.all('tasks') if (t.get('plan') or {}).get('rename_receipt')], [])
        self.assertEqual(self.plex.uploads, [])

    def test_plex_not_yet_associated_is_pending_not_a_rematch_or_refresh(self):
        receipt, view = self.lost_after_rematch()
        self.plex.rows.pop('100')
        with patch.object(self.plex, 'refresh', create=True) as refresh:
            with self.assertRaisesRegex(UserError, "after Plex's next scan"):
                self.service.restore_rename_artwork(view['id'], view['version'], ['cover'])
        refresh.assert_not_called()
        self.assertEqual(self.plex.uploads, [])

    def test_portrait_restore_changes_only_the_selected_person(self):
        receipt, view = self.lost_after_rematch()
        person = next(p for p in view['portraits'] if p['name'] == 'Person')
        restored = self.service.restore_rename_portraits(
            view['id'], view['version'], [person['index']], view['cast_digest']
        )
        roles = self.plex.rows['100']['Role']
        self.assertEqual([r['tag'] for r in roles], ['Person', 'Guest', 'Friend'])
        self.assertEqual(self.plex.pictures[roles[0]['thumb']], PERSON)
        self.assertTrue(roles[0]['thumb'].startswith('/library/metadata/100/'))
        self.assertEqual(roles[1]['thumb'], 'https://agent.example/guest.jpg')
        self.assertEqual(roles[2]['thumb'], '')
        self.assertEqual([r['role'] for r in roles], ['Self', 'Host', ''])
        after = next(p for p in restored['portraits'] if p['name'] == 'Person')
        self.assertEqual((after['restore']['state'], after['can_restore']), ('restored', False))
        self.assertEqual(self.plex.images['100', 'cover'], AGENT_POSTER)  # Artwork untouched.

    def test_portrait_restore_refuses_a_removed_person_and_newer_cast_changes(self):
        receipt, view = self.lost_after_rematch()
        self.plex.rows['100']['Role'].append({'tag': 'Newcomer', 'role': '', 'thumb': ''})
        with self.assertRaisesRegex(UserError, 'newer cast changes'):
            self.service.restore_rename_portraits(view['id'], view['version'], [0], view['cast_digest'])
        with self.assertRaisesRegex(UserError, 'cast changed since you opened'):
            self.service.restore_rename_portraits(view['id'], view['version'], [0], 'stale')
        self.assertEqual(self.plex.uploads, [])
        # A person Plex no longer credits is reported, and never re-added through a picture restore.
        self.plex.rows['100']['Role'] = [
            r for r in self.plex.rows['100']['Role'] if r['tag'] not in {'Person', 'Newcomer'}
        ]
        self.scan()
        with self.store.transaction():
            latest = self.store.get('settings', receipt['id'])
            latest['outcome']['portraits'] = {'Person': 'person_missing'}
            self.store.put('settings', latest['id'], latest)
        view = self.service.rename_receipt_view(receipt['receipt'])
        person = next(p for p in view['portraits'] if p['name'] == 'Person')
        self.assertEqual((person['state'], person['can_restore']), ('person_missing', False))
        with self.assertRaisesRegex(UserError, 'no longer credited'):
            self.service.restore_rename_portraits(view['id'], view['version'], [0], view['cast_digest'])
        self.assertEqual(self.plex.uploads, [])

    def test_a_cast_edit_landing_during_the_restore_is_kept_and_nothing_is_written(self):
        """Codex #158 P1: a newer cast that lands after the receipt check must never be overwritten."""
        cases = {
            'new credit': lambda roles: roles.append({'tag': 'Newcomer', 'role': 'Guest star', 'thumb': ''}),
            'role': lambda roles: roles[1].update(role='Co-host'),
            'order': lambda roles: roles.reverse(),
            'photo': lambda roles: roles[2].update(thumb='https://agent.example/friend.jpg'),
        }
        for name, change in cases.items():
            with self.subTest(change=name):
                self.tearDown()
                self.setUp()
                receipt, view = self.lost_after_rematch()
                real_task = self.service.metadata_task

                def edit_lands_first(asset_id):
                    # Another approved edit reaches Plex and the cache between the receipt check and the save.
                    task = real_task(asset_id)
                    change(self.plex.rows['100']['Role'])
                    with self.store.transaction():
                        asset = self.store.get('assets', asset_id)
                        asset['item'] = copy.deepcopy(self.plex.rows['100'])
                        self.store.put('assets', asset_id, asset)
                    return task

                newer = None
                with patch.object(self.service, 'metadata_task', side_effect=edit_lands_first):
                    with self.assertRaisesRegex(UserError, 'changed since you reviewed'):
                        self.service.restore_rename_portraits(view['id'], view['version'], [0], view['cast_digest'])
                newer = copy.deepcopy(self.plex.rows['100']['Role'])
                self.assertEqual(self.plex.uploads, [])
                self.assertEqual(self.plex.rows['100']['Role'], newer)
                person = next(
                    p for p in self.service.rename_receipt_view(view['id'])['portraits'] if p['name'] == 'Person'
                )
                self.assertEqual(person['restore']['state'], 'failed')

    def test_apply_cast_without_a_reviewed_digest_keeps_its_existing_behaviour(self):
        task = self.service.metadata_task(self.assets[0]['id'])
        rows = [
            dict(name=r['name'], role=r['role'], thumb=r['thumb'])
            for r in self.service.metadata_fields(self.plex.rows['1'])['cast']
        ]
        rows[1]['role'] = 'Presenter'
        self.service.apply_cast(task['id'], task['version'], rows)
        self.assertEqual(self.plex.rows['1']['Role'][1]['role'], 'Presenter')

    def test_failed_portrait_upload_is_reported_and_the_retained_picture_is_kept(self):
        receipt, view = self.lost_after_rematch()

        def broken(key, image):
            raise PlexError('Plex did not identify one new cast picture; inspect before retrying')

        self.plex.cast_photo = broken
        with self.assertRaisesRegex(UserError, 'still in the receipt'):
            self.service.restore_rename_portraits(view['id'], view['version'], [0], view['cast_digest'])
        after = next(p for p in self.service.rename_receipt_view(view['id'])['portraits'] if p['name'] == 'Person')
        self.assertEqual(after['restore']['state'], 'failed')
        self.assertTrue(after['can_restore'])  # A failed attempt can be tried again after inspection.
        self.assertEqual(self.plex.rows['100']['Role'][0]['thumb'], 'https://agent.example/person.jpg')
        self.assertEqual(self.service.retained_rename_portrait(receipt, 0), PERSON)


if __name__ == '__main__':
    unittest.main()
