#!/bin/bash
# Initialize the state database

export PYTHONPATH="."
python -m app.cli --config config.yaml init-db
