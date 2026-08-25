#!/bin/bash
# Executable launcher for Screen Capture & Recording Software
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
exec python3 src/main.py "$@"
