#!/usr/bin/env python3
"""Install Curator as a per-user macOS LaunchAgent on a dedicated Mac.

Defaults to loopback; private-network listening requires explicit host options.
"""
import argparse
import os
import plistlib
import sys
from pathlib import Path


LABEL = "com.curator.foundry"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_properties(root, state, port, python, host="127.0.0.1", expected_hosts=()):
    from curator.web import listener_settings
    host, expected_hosts = listener_settings(host, expected_hosts)
    arguments = [python, "-m", "curator.web", "--state", str(state), "--port", str(port), "--host", host]
    for name in expected_hosts:
        arguments.extend(["--expected-host", name])
    return {
        "Label": LABEL,
        "ProgramArguments": arguments,
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
    parser.add_argument("--host", default="127.0.0.1", help="Explicit loopback or RFC1918 IPv4 bind address")
    parser.add_argument("--expected-host", action="append", default=[], help="Additional bare browser hostname")
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
    agents = Path.home() / "Library" / "LaunchAgents"
    destination = agents / (LABEL + ".plist")
    if destination.is_symlink():
        parser.error("Existing LaunchAgent is a symlink; preserving it")
    if destination.exists() and not args.replace:
        parser.error(f"{destination} already exists; pass --replace to overwrite it")
    try:
        properties = make_properties(root, state, args.port, sys.executable, args.host, args.expected_host)
    except ValueError as error:
        parser.error(str(error))
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    agents.mkdir(parents=True, exist_ok=True)
    with destination.open("wb" if args.replace else "xb") as output:
        plistlib.dump(properties, output)
    destination.chmod(0o600)
    print(f"Created: {destination}")
    print(f"Configured bind: {args.host}:{args.port}; expected browser names: {', '.join(args.expected_host) or '(bind address only)'}")
    print("For a LAN bind, enforce the approved private-client firewall policy before starting.")
    print("After stopping any manually running Curator instance, load the agent:")
    print(f'  launchctl bootstrap gui/$(id -u) "{destination}"')
    print(f"  launchctl kickstart -k gui/$(id -u)/{LABEL}")
    print(f"  launchctl print gui/$(id -u)/{LABEL}")
    print("The LaunchAgent starts within this user's logged-in GUI session.")
    print("No media processing tools are installed by this script.")


if __name__ == "__main__":
    main()
