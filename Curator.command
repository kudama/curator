#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
if [[ -x /opt/homebrew/bin/python3 ]]; then
  exec /opt/homebrew/bin/python3 -m curator.web --open
fi
exec python3 -m curator.web --open
