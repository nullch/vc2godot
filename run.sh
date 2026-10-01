#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python -m venv .venv
fi
source .venv/bin/activate
pip install -e .
exec vc2godot "$@"
