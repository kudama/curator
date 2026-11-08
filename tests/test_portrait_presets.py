import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from curator.tools import freeze_handbrake_preset

class PortraitPresets(unittest.TestCase):
    def test_landscape_limits_swap_only_for_portrait_source(self):
        preset={'PresetName':'Curator approved preset','Folder':False,'PictureWidth':1920,'PictureHeight':1080,'PicturePAR':'auto'}
        payload=json.dumps({'PresetList':[preset]})
        with tempfile.TemporaryDirectory() as folder, \
             patch('curator.tools.handbrake_presets',return_value={'executable':'fake','presets':[{'path':'General/Fast 1080p30'}]}), \
             patch('curator.tools.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=payload)):
            settings=freeze_handbrake_preset({},'General/Fast 1080p30',folder,{'width':1296,'height':2304})
            frozen=json.loads(Path(settings['handbrake_preset_file']).read_text())['PresetList'][0]
            self.assertEqual((frozen['PictureWidth'],frozen['PictureHeight']),(1080,1920))
            self.assertEqual(frozen['PicturePAR'],'off')
            self.assertFalse(frozen['PictureAllowUpscaling'])
            self.assertEqual(settings['handbrake_geometry']['orientation'],'portrait')
            settings=freeze_handbrake_preset({},'General/Fast 1080p30',folder,{'width':1920,'height':1080})
            frozen=json.loads(Path(settings['handbrake_preset_file']).read_text())['PresetList'][0]
            self.assertEqual(frozen,preset)
            self.assertIsNone(settings['handbrake_geometry'])
