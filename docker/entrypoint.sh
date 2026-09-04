#!/usr/bin/env bash
set -euo pipefail

cd /app
exec /usr/bin/python3 tools/clone_live.py "$@"
