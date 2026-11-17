import unittest
from unittest.mock import patch
from curator.tools import topaz_encoding,command


class EncodingControls(unittest.TestCase):
    def test_default_quality_is_preserved_and_bitrate_mode_has_no_quality_argument(self):
        self.assertEqual(topaz_encoding({}),['-q:v','65'])
        settings={'topaz_filter':'tvai_up=model=prob-4:scale=2','topaz_rate_control':'bitrate','topaz_bitrate_mbps':'8'}
        with patch('curator.tools.executable',return_value='/tools/ffmpeg'):args=command('upscale','input.mp4','output.mp4',settings)
        self.assertNotIn('-q:v',args);self.assertEqual(args[args.index('-b:v')+1],'8000000')
        self.assertEqual(args[args.index('-maxrate')+1],'8000000');self.assertIn('hvc1',args)
        self.assertEqual(args[args.index('-c:a')+1],'copy')
    def test_invalid_values_cannot_reach_encoder(self):
        for settings in [{'topaz_rate_control':'shell'},{'topaz_quality':'65;echo bad'},{'topaz_quality':True},
                         {'topaz_quality':0},{'topaz_quality':101},{'topaz_rate_control':'bitrate','topaz_bitrate_mbps':float('nan')},
                         {'topaz_rate_control':'bitrate','topaz_bitrate_mbps':0},{'topaz_rate_control':'bitrate','topaz_bitrate_mbps':501}]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):topaz_encoding(settings)

    def test_quality_and_bitrate_container_arguments(self):
            settings = {
                'topaz_filter': 'tvai_up=model=prob-4:scale=2',
                'topaz_rate_control': 'quality',
                'topaz_quality': '85'
            }
            with patch('curator.tools.executable', return_value='/tools/ffmpeg'):
                args = command('upscale', 'input.mp4', 'output.mp4', settings)
                self.assertIn('-q:v', args)
                self.assertEqual(args[args.index('-q:v') + 1], '85')
                self.assertNotIn('-b:v', args)

            settings['topaz_rate_control'] = 'bitrate'
            settings['topaz_bitrate_mbps'] = '8'

            with patch('curator.tools.executable', return_value='/tools/ffmpeg'):
                args = command('upscale', 'input.mp4', 'output.mp4', settings)
                self.assertIn('-b:v', args)
                self.assertEqual(args[args.index('-b:v') + 1], '8000000')
                self.assertIn('hvc1', args)
                for option in ('-c:a','-c:s'):
                    self.assertEqual(args[args.index(option)+1], 'copy')

            with patch('curator.tools.executable', return_value='/tools/ffmpeg'):
                args = command('upscale', 'input.mp4', 'output.mkv', settings)
                self.assertIn('-b:v', args)
                self.assertEqual(args[args.index('-b:v') + 1], '8000000')
                self.assertNotIn('hvc1', args)
