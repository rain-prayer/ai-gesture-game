#!/usr/bin/env sh
# Launch AI Gesture Jump (needs a webcam).
cd "$(dirname "$0")" || exit 1
exec python3 game/main.py "$@"
