#!/bin/bash
# Finder-compatible fallback. It uses the same persistent library as the native app.
set -eu
STUDIO_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    candidate="$(command -v python3 || true)"
    if [ -n "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
    fi
fi
if [ -z "$PYTHON_BIN" ]; then
    printf '%s\n' 'YuE Studio needs Python 3.10 or newer.' 'Install Python 3.12 from https://www.python.org/downloads/macos/ or run: brew install python@3.12' 'Then double-click this launcher again.'
    read -r -p 'Press Return to close. ' _response
    exit 1
fi
exec "$PYTHON_BIN" "$STUDIO_DIR/macos/browser_launcher.py"
