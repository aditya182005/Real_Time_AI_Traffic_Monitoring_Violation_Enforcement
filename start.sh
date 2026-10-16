#!/usr/bin/env sh
# Start the dashboard. Run ./setup.sh first (only needed once).
cd "$(dirname "$0")"
[ -f venv/bin/activate ] || { echo "No venv yet. Run ./setup.sh first."; exit 1; }
. venv/bin/activate
exec streamlit run app/main.py
