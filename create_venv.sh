#!/bin/bash

python3.6 -m venv venv
source venv/bin/activate
python3.6 -m pip install -r requirements.txt
python3.6 -m pip install -r requirements_admin.txt
