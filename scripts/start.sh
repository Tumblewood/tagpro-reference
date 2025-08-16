#!/bin/bash

# Kill existing uwsgi process
pkill -f "uwsgi.*tagproref.wsgi" 2>/dev/null

# Load environment variables from .env
if [ -f .env ]; then
   export $(grep -v '^#' .env | xargs)
fi

# Collect static files
python manage.py collectstatic --noinput

# Start uwsgi
uwsgi --socket /home/venv-tpr/tagpro-reference/tagpro-reference.sock \
     --module tagproref.wsgi \
     --chmod-socket=666 \
     --master \
     --processes=4 \
     --threads=2 \
     --vacuum \
     --die-on-term \
     --daemonize /home/venv-tpr/tagpro-reference/logs/uwsgi.log