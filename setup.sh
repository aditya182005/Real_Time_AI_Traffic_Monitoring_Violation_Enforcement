#!/usr/bin/env sh
# One-time setup (safe to run again): creates the venv and installs everything.
set -e
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
. venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo
echo "Setup finished. Check it with:  venv/bin/python scripts/check_setup.py --full"
echo "Then start the app with:        ./start.sh"
