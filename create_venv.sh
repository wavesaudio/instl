#!/bin/bash

python3.9 -m venv venv
source venv/bin/activate
python3.9 -m pip install -r requirements.txt
python3.9 -m pip install -r requirements_admin.txt
