#!/bin/bash
set -euo pipefail
sudo pacman -S --needed python python-pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
echo
 echo 'Installed. Use: source .venv/bin/activate && vc2godot scan /path/to/Vice\ City'
