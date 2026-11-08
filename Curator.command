#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
for curator_python in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3 || true)"; do
  if [[ -x "$curator_python" ]] && "$curator_python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    exec "$curator_python" -m curator.web --open "$@"
  fi
done
print -u2 'Curator requires Python 3.11 or newer. Install Python for macOS, then reopen Curator.command.'
exit 1
