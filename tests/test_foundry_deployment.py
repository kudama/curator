"""Foundry startup configuration has explicit private-network opt-in."""

import importlib.util
import plistlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install-foundry-launchagent.py"
SPEC = importlib.util.spec_from_file_location("foundry_launchagent", SCRIPT)
foundry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(foundry)


class FoundryLaunchAgent(unittest.TestCase):
    def test_agent_runs_existing_loopback_server_with_local_state(self):
        root = Path("/Users/test/src/curator")
        state = Path("/Users/test/Library/Application Support/Curator")
        properties = foundry.make_properties(root, state, 8790, "/opt/homebrew/bin/python3")
        self.assertEqual(
            properties["ProgramArguments"],
            [
                "/opt/homebrew/bin/python3",
                "-m",
                "curator.web",
                "--state",
                str(state),
                "--port",
                "8790",
                "--host",
                "127.0.0.1",
                "--managed-service",
            ],
        )
        self.assertNotIn("--expected-host", properties["ProgramArguments"])
        self.assertEqual(properties["WorkingDirectory"], str(root))
        self.assertTrue(properties["RunAtLoad"])
        self.assertEqual(properties["KeepAlive"], {"SuccessfulExit": False})

    def test_plist_encoding_and_custom_port(self):
        props = foundry.make_properties(
            Path("/tmp/Curator & tools"), Path("/tmp/Curator & state"), 8877, "/usr/bin/python3"
        )
        decoded = plistlib.loads(plistlib.dumps(props))
        self.assertEqual(decoded["ProgramArguments"][decoded["ProgramArguments"].index("--port") + 1], "8877")
        self.assertEqual(decoded["Label"], "com.curator.foundry")
        self.assertIn("Curator & state", decoded["StandardErrorPath"])

    def test_private_bind_and_multiple_hostnames_are_separate_arguments(self):
        props = foundry.make_properties(
            Path('/src/curator'), Path('/local/state'), 8790, '/python', '10.0.0.106', ['foundry', 'foundry.tfs.apt']
        )
        args = plistlib.loads(plistlib.dumps(props))['ProgramArguments']
        self.assertEqual(
            args[-7:],
            [
                '--host',
                '10.0.0.106',
                '--managed-service',
                '--expected-host',
                'foundry',
                '--expected-host',
                'foundry.tfs.apt',
            ],
        )

    def test_invalid_binding_is_refused(self):
        with self.assertRaises(ValueError):
            foundry.make_properties(Path('/src'), Path('/state'), 8790, '/python', '0.0.0.0')

    def test_cli_invalid_host_does_not_create_state(self):
        import io
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            with (
                patch.object(foundry.sys, 'platform', 'darwin'),
                patch.object(foundry.sys, 'argv', ['installer', '--state', str(state), '--host', '0.0.0.0']),
                patch('sys.stderr', new_callable=io.StringIO),
            ):
                with self.assertRaises(SystemExit):
                    foundry.main()
            self.assertFalse(state.exists())

    def test_existing_plist_or_symlink_is_preserved_before_state_creation(self):
        import io
        import tempfile
        from unittest.mock import patch

        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                state = home / 'state'
                destination = home / 'Library/LaunchAgents' / (foundry.LABEL + '.plist')
                destination.parent.mkdir(parents=True)
                if symlink:
                    destination.symlink_to(home / 'absent')
                else:
                    destination.write_bytes(b'preserve existing service')
                with (
                    patch.object(foundry.sys, 'platform', 'darwin'),
                    patch.object(foundry.sys, 'argv', ['installer', '--state', str(state)]),
                    patch.object(foundry.Path, 'home', return_value=home),
                    patch('sys.stderr', new_callable=io.StringIO),
                ):
                    with self.assertRaises(SystemExit):
                        foundry.main()
                self.assertFalse(state.exists())
                if symlink:
                    self.assertTrue(destination.is_symlink())
                else:
                    self.assertEqual(destination.read_bytes(), b'preserve existing service')


if __name__ == "__main__":
    unittest.main()
