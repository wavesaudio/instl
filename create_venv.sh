#!/bin/bash

python3.12 -m venv venv
source venv/bin/activate
python3.12 -m pip install --upgrade pip
python3.12 -m pip install -r requirements.txt
python3.12 -m pip install -r requirements_mac_only.txt
