#!/bin/sh
# One-command sync for Linux/macOS: ./sync.sh [--dry-run] [--only claude pi] [--no-probe]
cd "$(dirname "$0")" || exit 1
exec python3 bootstrap.py "$@"
