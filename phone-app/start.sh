#!/bin/bash
# PLC Project Container Startup Script
# Ensures proper initialization order

set -e

echo "🚀 Starting PLC Project Container..."

# Start supervisord which will handle all services
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf