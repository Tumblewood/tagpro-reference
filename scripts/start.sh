#!/bin/bash

# Set script to exit on any error
set -e

# Change to the project directory (assumes script is run from project root)
cd "$(dirname "$0")/.."

# Production environment variables
# IMPORTANT: Set these environment variables for production deployment
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-False}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-localhost,127.0.0.1}"
export DJANGO_STATIC_ROOT="${DJANGO_STATIC_ROOT:-/var/www/tagpro-reference/staticfiles}"

# Kill any existing uwsgi processes for this project
echo "Stopping existing uwsgi processes..."
pkill -f "uwsgi.*tagpro-reference" || echo "No existing uwsgi processes found"

# Collect static files
echo "Collecting static files..."
python3 manage.py collectstatic --no-input

# Restart nginx
echo "Restarting nginx..."
sudo /etc/init.d/nginx restart

# Create log directory if it doesn't exist
sudo mkdir -p /var/log/uwsgi

# Create static files directory if it doesn't exist
sudo mkdir -p "$DJANGO_STATIC_ROOT"
sudo chown -R www-data:www-data "$DJANGO_STATIC_ROOT"

# Start uwsgi with the application
echo "Starting uwsgi..."
uwsgi --socket tagpro-reference.sock \
      --module tplnext.wsgi \
      --chmod-socket=666 \
      --daemonize=/var/log/uwsgi/tagpro-reference.log \
      --env DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" \
      --env DJANGO_DEBUG="$DJANGO_DEBUG" \
      --env DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
      --env DJANGO_STATIC_ROOT="$DJANGO_STATIC_ROOT"

echo "Application started successfully!"
echo "Socket file: tagpro-reference.sock"
echo "Log file: /var/log/uwsgi/tagpro-reference.log"
echo ""
echo "To check if the application is running:"
echo "  ps aux | grep uwsgi | grep tagpro-reference"
echo ""
echo "To view logs:"
echo "  tail -f /var/log/uwsgi/tagpro-reference.log"