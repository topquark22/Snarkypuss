#!/bin/bash

python3 -m build --wheel

sudo /usr/lib/snarkyctl/venv/bin/pip install --force-reinstall \
    dist/snarkyctl-0.1.0.dev2-py3-none-any.whl

sudo systemctl stop snarkyctl-control.service
sudo systemctl restart snarkyctl-control.socket
sudo systemctl restart snarkyctl-web.service
