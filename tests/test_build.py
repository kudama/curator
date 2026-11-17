import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.build import capture_build, RUNNING_BUILD, VERSION
from curator.runtime import ServiceRuntime
from types import SimpleNamespace


class BuildIdentity(unittest.TestCase):
    def test_known_revision_is_captured_and_status_returns_a_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            responses=[folder, 'a'*40, ' M curator/web.py']
            with patch('curator.build.subprocess.run',side_effect=[SimpleNamespace(stdout=x) for x in responses]):
                build=capture_build(folder)
            self.assertEqual(build['revision'],'a'*40)
            self.assertTrue(build['dirty'])
            service=SimpleNamespace(active=set(),scan_status={},presence_status={},store=SimpleNamespace(all=lambda _:[]))
            with patch('curator.runtime.RUNNING_BUILD',build):runtime=ServiceRuntime(service)
            with patch('curator.build.subprocess.run',side_effect=AssertionError('Must not reread checkout')):
                result=runtime.status()['build'];result['revision']='changed'
                self.assertEqual(runtime.status()['build']['revision'],'a'*40)

    def test_missing_git_or_timeout_reports_unknown(self):
        for error in [FileNotFoundError(),subprocess.TimeoutExpired('git',2)]:
            with patch('curator.build.subprocess.run',side_effect=error):build=capture_build()
            self.assertEqual(build['version'],VERSION)
            self.assertEqual(build['revision'],'unknown')
            self.assertIsNone(build['dirty'])

    def test_zip_inside_unrelated_checkout_does_not_claim_parent_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('curator.build.subprocess.run',return_value=SimpleNamespace(stdout=folder)) as run:
                build=capture_build(Path(folder)/'extracted')
            self.assertEqual(build['revision'],'unknown');self.assertEqual(run.call_count,1)
