import tempfile
import unittest
from pathlib import Path
from curator.progress import encoder_status, EncodingProgress


class EncoderProgress(unittest.TestCase):
    def test_handbrake_reported_eta_and_fps(self):
        p=encoder_status('Encoding: task 1 of 1, 25.00 % (32.00 fps, avg 30.00 fps, ETA 00h02m30s)','optimize',600,60)
        self.assertEqual(p['percent'],25);self.assertEqual(p['eta_seconds'],150);self.assertEqual(p['fps'],32)

    def test_handbrake_multipass_estimates_whole_encode(self):
        p=encoder_status('Encoding: task 2 of 2, 50.00 % (ETA 00h00m10s)','optimize',600,300)
        self.assertEqual(p['percent'],75);self.assertEqual(p['eta_seconds'],100)

    def test_ffmpeg_speed_drives_remaining_time(self):
        p=encoder_status('frame= 600 fps= 12 time=00:01:00.00 bitrate=2000kbits/s speed=0.5x','upscale',180,120)
        self.assertAlmostEqual(p['percent'],100/3);self.assertEqual(p['eta_seconds'],240);self.assertEqual(p['fps'],12)

    def test_last_carriage_return_record_wins(self):
        p=encoder_status('frame=1 time=00:00:01.00 speed=1x\rframe=2 time=00:00:20.00 speed=2x\r','upscale',100,40)
        self.assertEqual(p['encoded_seconds'],20);self.assertEqual(p['eta_seconds'],40)

    def test_average_speed_fallback_after_warmup(self):
        p=encoder_status('frame=1 time=00:00:20.00 speed=N/A','upscale',100,40)
        self.assertEqual(p['eta_seconds'],160)
        p=encoder_status('frame=1 time=00:00:00.00 speed=N/A','upscale',100,1)
        self.assertIsNone(p['eta_seconds'])

    def test_missing_duration_invalid_or_scanning_status_has_no_fake_eta(self):
        self.assertIsNone(encoder_status('Scanning title 1, 80 %','optimize',100,30))
        self.assertIsNone(encoder_status('time=00:00:10.00 speed=1x','upscale',0,30))
        self.assertIsNone(encoder_status('Encoding: task 0 of 0, 50 %','optimize',100,30))
        self.assertIsNone(encoder_status('Encoding: task 1 of 1, 999 %','optimize',100,30))

    def test_percentage_and_remaining_time_clamp_at_encode_end(self):
        p=encoder_status('time=00:02:00.00 speed=1x','upscale',100,120)
        self.assertEqual(p['percent'],100);self.assertEqual(p['eta_seconds'],0)

    def test_incremental_reader_stale_status_and_split_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tool.log';path.write_text('Encoding: task 1 of 1, 25.00 % (ETA 00h')
            progress=EncodingProgress('optimize',600);progress.read(path,1)
            with path.open('a') as out:out.write('02m30s)\r')
            self.assertEqual(progress.read(path,2)['eta_seconds'],150)
            self.assertIsNone(progress.read(path,20)['eta_seconds'])
            with path.open('a') as out:out.write('Encoding: task 1 of 1, 50.00 % (ETA 00h01m00s)\r')
            self.assertEqual(progress.read(path,21)['eta_seconds'],60)

    def test_missing_log_is_indeterminate(self):
        p=EncodingProgress('upscale',100).read(Path('/no/such/curator-test-log'),10)
        self.assertIsNone(p['eta_seconds']);self.assertNotIn('percent',p)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tool.log';path.write_text('Encoding: task 1 of 1, 2..5 %')
            self.assertIsNone(EncodingProgress('optimize',100).read(path,10)['eta_seconds'])

    def test_reader_bounds_large_logs_and_handles_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tool.log';path.write_text('x'*100000+'\ntime=00:00:20.00 speed=1x\n')
            progress=EncodingProgress('upscale',100)
            self.assertEqual(progress.read(path,20)['eta_seconds'],80);self.assertLessEqual(len(progress.tail),65536)
            path.write_text('starting over')
            self.assertNotIn('percent',progress.read(path,21))
