#!/bin/bash

SCRIPT="${BASH_SOURCE[0]}"
SCRIPT_FOLDER=$(dirname $SCRIPT)

#export PYTHONPATH=${SCRIPT_FOLDER}:${SCRIPT_FOLDER}/pybatch:${SCRIPT_FOLDER}/pybatch/test:${PYTHONPATH}

echo ${PYTHONPATH}

source "${SCRIPT_FOLDER}/venv/bin/activate"
sudo python3.9 "$@"
