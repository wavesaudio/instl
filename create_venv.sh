#!/bin/bash

echo ---* creating virtual env in $(pwd) *---

python3.12 -m venv venv
source venv/bin/activate

echo ---* pip installing *---

python3.12 -m pip install --upgrade pip
python3.12 -m pip install -r requirements_mac_only.txt
python3.12 -m pip install -r requirements.txt

echo ---* creating virtual env done *---
