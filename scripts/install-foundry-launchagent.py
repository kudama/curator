#!/usr/bin/env python3
"""Install Curator as a per-user macOS LaunchAgent on a dedicated Mac.

Does not enable network listening: remote browsers use SSH port forwarding.
"""
import argparse
import os
import plistlib
import sys
from pathlib import Path


LABEL = "com.curator.foundry"


def make_properties(root, state, port, python):
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "curator.web",
                             "--state", str(state), "--port", str(port)],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(state / "launchd.stdout.log"),
        "StandardErrorPath": str(state / "launchd.stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a Curator launchd LaunchAgent")
    parser.add_argument("--state", default="~/Library/Application Support/Curator",
                        help="Local (not network) Curator state directory")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--replace", action="store_true",
                        help="Replace an existing generated LaunchAgent file")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("LaunchAgent installation requires macOS")
    if sys.version_info < (3, 11):
        parser.error("Curator requires Python 3.11 or newer")
    if not (1 <= args.port <= 65535):
        parser.error("Port must be between 1 and 65535")

    root = Path(__file__).resolve().parent.parent
    state = Path(args.state).expanduser().resolve()
    if state == root or root.is_relative_to(state):
        parser.error("State must not contain the Curator source tree")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    destination = agents / (LABEL + ".plist")
    if destination.exists() and not args.replace:
        parser.error(f"{destination} already exists; pass --replace to overwrite it")

    properties = make_properties(root, state, args.port, sys.executable)
    with destination.open("wb") as output:
        plistlib.dump(properties, output)
    destination.chmod(0o600)
    print(f"Created: {destination}")
    print("Curator remains localhost-only; access remotely using an SSH tunnel.")
    print("After stopping any manually running Curator instance, load the agent:")
    print(f'  launchctl bootstrap gui/$(id -u) "{destination}"')
    print(f"  launchctl kickstart -k gui/$(id -u)/{LABEL}")
    print(f"  launchctl print gui/$(id -u)/{LABEL}")
    print("The LaunchAgent starts within this user's logged-in GUI session.")
    print("No media processing tools are installed by this script.")


if __name__ == "__main__":
    main()
