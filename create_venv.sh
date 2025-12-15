#!/bin/bash

echo ---* python is: $(which python3.12) *---

echo ---* creating virtual env in: $(pwd)/venv *---

python3.12 -m venv venv
source venv/bin/activate
echo ---* after "source venv/bin/activate" VIRTUAL_ENV is:
echo    $VIRTUAL_ENV  *---

echo ---* activated virtual env in: $(pwd)/venv *---
echo ---* now python is: $(which python3.12) *---

echo ---* pip installing *---

# pip install mac requirements first, so universal binaries will get priority
python3.12 -m pip install --upgrade pip  --no-user
python3.12 -m pip install -r requirements_mac_only.txt  --no-user
python3.12 -m pip install -r requirements.txt  --no-user

echo ---* creating virtual env done *---
