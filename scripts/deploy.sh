#!/bin/bash
# Deploys whatever is checked out. Run after `git pull`:
#     bash scripts/deploy.sh
# The site runs as the systemd service tagpro-reference (see
# scripts/tagpro-reference.service); logs: journalctl -u tagpro-reference
# Settings come from .env (loaded by settings.py).
set -e
cd "$(dirname "$0")/.."

export UV_PYTHON_INSTALL_DIR=/opt/uv/python
[ -d .venv ] || uv venv --python 3.13 .venv
uv pip install --python .venv -r requirements.txt
.venv/bin/python manage.py collectstatic --noinput
systemctl restart tagpro-reference
systemctl is-active tagpro-reference
