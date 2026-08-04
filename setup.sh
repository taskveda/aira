#!/bin/bash
set -e
cd "$(dirname "$0")"

PY=$(command -v /usr/local/bin/python3.14 || command -v python3.14 || command -v python3.11 || command -v python3)
echo "Using $PY"

[ -d venv ] || "$PY" -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

mkdir -p data/history data/audio

echo ""
echo "Ras installed. Next steps:"
echo "  1. Edit config.yaml (provider, channel, jobs)"
echo "  2. Export secrets (see README: slack tokens, DEEPSEEK_API_KEY)"
echo "  3. Try without Slack:  ./venv/bin/python -m ras.main --cli"
echo "  4. Run live:           ./venv/bin/python -m ras.main"
