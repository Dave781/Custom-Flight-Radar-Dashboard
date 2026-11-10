#!/bin/bash
# Quick run script for testing (without systemd)
cd "$(dirname "$0")"
if [ -x venv/bin/python3 ]; then
    exec venv/bin/python3 app.py
fi
exec python3 app.py
