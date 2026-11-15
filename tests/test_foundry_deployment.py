"""Foundry startup configuration stays localhost-only and standalone-safe."""
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
        self.assertEqual(properties["ProgramArguments"], [
            "/opt/homebrew/bin/python3", "-m", "curator.web",
            "--state", str(state), "--port", "8790"
        ])
        self.assertNotIn("--host", properties["ProgramArguments"])
        self.assertEqual(properties["WorkingDirectory"], str(root))
        self.assertTrue(properties["RunAtLoad"])
        self.assertEqual(properties["KeepAlive"], {"SuccessfulExit": False})

    def test_plist_encoding_and_custom_port(self):
        props = foundry.make_properties(Path("/tmp/Curator & tools"),
                                        Path("/tmp/Curator & state"), 8877, "/usr/bin/python3")
        decoded = plistlib.loads(plistlib.dumps(props))
        self.assertEqual(decoded["ProgramArguments"][-1], "8877")
        self.assertEqual(decoded["Label"], "com.curator.foundry")
        self.assertIn("Curator & state", decoded["StandardErrorPath"])


if __name__ == "__main__":
    unittest.main()
