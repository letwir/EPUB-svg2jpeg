#!/bin/bash
sudo apt update
sudo apt -y install python3-venv
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
echo "python3 convert.py -i SRC -o DST -j $(nproc) -f /path/to/ttf/hoge.ttf"
exit 0
