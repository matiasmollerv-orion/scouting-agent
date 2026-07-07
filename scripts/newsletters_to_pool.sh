#!/bin/bash
# Empuja newsletters de GBrain al scouting. Corre diario vía LaunchAgent.
cd "$HOME/scouting-agent" || exit 1
source .venv/bin/activate
python scripts/newsletters_to_pool.py >> logs/newsletters.log 2>&1
