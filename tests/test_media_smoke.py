"""Actual local FFmpeg probe/frame smoke check, using generated test patterns only."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from curator.tools import TOPAZ, probe, frames, handbrake_presets, freeze_handbrake_preset, command


@unittest.skipUnless(os.path.isfile(TOPAZ+'ffmpeg'), 'Topaz FFmpeg not installed on this host')
class MediaSmoke(unittest.TestCase):
    def test_generated_pattern_can_be_probed_and_sampled(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'pattern.mkv'
            subprocess.run([TOPAZ+'ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                            'testsrc2=size=640x360:rate=2','-t','2','-c:v','ffv1',str(source)],
                           check=True,capture_output=True,timeout=30)
            media=probe(source,{})
            self.assertEqual((media['width'],media['height']),(640,360))
            candidates=frames(source,Path(folder)/'frames',media,{})
            self.assertGreaterEqual(len(candidates),2)
            for frame in candidates:
                self.assertTrue((Path(folder)/'frames'/frame['file']).is_file())


@unittest.skipUnless(os.path.isfile('/Applications/HandBrakeCLI'),'HandBrakeCLI not installed on this host')
class HandBrakeSmoke(unittest.TestCase):
    def test_actual_preset_list_and_snapshot_import_without_encoding(self):
        result=handbrake_presets({'handbrake':'/Applications/HandBrakeCLI'})
        self.assertGreater(len(result['presets']),5)
        selected=next(x for x in result['presets'] if x['name']=='H.265 Apple VideoToolbox 1080p')
        with tempfile.TemporaryDirectory() as folder:
            settings=freeze_handbrake_preset({'handbrake':'/Applications/HandBrakeCLI'},selected['path'],folder)
            args=command('optimize','unused.mp4','unused-output.mp4',settings)
            self.assertIn('--preset-import-file',args)
            self.assertEqual(settings['handbrake_preset_source'],selected['path'])
            captured=Path(settings['handbrake_preset_file'])
            self.assertTrue(captured.is_file())
            # Demonstrate that the captured preset, rather than mutable GUI settings, loads.
            result=subprocess.run(['/Applications/HandBrakeCLI','--preset-import-file',str(captured),
                                   '--preset','Curator approved preset','--preset-export','Round trip'],
                                  capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0)

    @unittest.skipUnless(os.path.isfile(TOPAZ+'ffmpeg'),'FFmpeg not installed')
    def test_generated_video_runs_through_approved_handbrake_task(self):
        from curator.store import Store
        from curator.service import Service
        from curator.tools import fingerprint, digest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'pattern.mkv'
            subprocess.run([TOPAZ+'ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                            'testsrc2=size=1920x1080:rate=2','-t','1','-c:v','ffv1',str(source)],
                           check=True,capture_output=True,timeout=30)
            original=digest(source)
            store=Store(root/'state')
            try:
                service=Service(store)
                service.save_config({'handbrake':'/Applications/HandBrakeCLI'})
                library=dict(id='synthetic:1',server='synthetic',key='1',type='movie',profile='commercial',
                             title='Synthetic test',mappings=[dict(plex_root='/source',local_root=str(root))])
                asset=dict(id='a'*24,library=library['id'],rating_key='1',title='Generated pattern',
                           item=dict(title='Generated pattern'),plex_path='/source/pattern.mkv',
                           local_path=str(source.resolve()),fingerprint=fingerprint(source),technical=probe(source,{}),present=True)
                with store.transaction():
                    store.put('libraries',library['id'],library);store.put('assets',asset['id'],asset)
                    task=service.task(asset,dict(kind='optimize',reason='Synthetic encode test'))
                task=service.edit_task(task['id'],{'handbrake_preset':'General/Fast 1080p30'},task['version'])
                service.action(task['id'],'queue',task['version'])
                service._execute(task['id'])
                result=service.get_task(task['id'])
                self.assertEqual(result['status'],'awaiting_review',result.get('error'))
                self.assertEqual(result['validation'],[])
                self.assertEqual(digest(source),original)
                self.assertTrue(Path(result['output']).is_file())
            finally:
                store.close()
