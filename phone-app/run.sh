#!/bin/bash
# PLC Project - Single Container Runner
# Run this to start the entire application automatically

set -e

echo "🚀 PLC Project - Single Container Runner"
echo "========================================"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if image exists locally
if ! docker images | grep -q "plc-project"; then
    log_info "Building PLC Project image..."
    docker build -f Dockerfile.single -t plc-project:latest .
else
    log_info "Using existing PLC Project image"
fi

# Stop any existing containers
log_info "Stopping existing containers..."
docker stop plc-app 2>/dev/null || true
docker rm plc-app 2>/dev/null || true

# Start the container
log_info "Starting PLC application..."
docker run -d \
    --name plc-app \
    -p 80:80 \
    --restart unless-stopped \
    plc-project:latest

# Wait for startup
log_info "Waiting for application to start..."
sleep 10

# Check if it's running
if docker ps | grep -q "plc-app"; then
    log_info "✅ PLC Application started successfully!"

    # Get container IP
    CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' plc-app 2>/dev/null || echo "localhost")

    echo ""
    echo "🌐 Application URLs:"
    echo "   Web Interface: http://localhost"
    echo "   API Health:    http://localhost/health/"
    echo "   Admin Panel:   http://localhost/admin/"
    echo ""
    echo "📱 Mobile apps are built automatically in CI/CD"
    echo ""
    echo "🔧 Management:"
    echo "   View logs:     docker logs -f plc-app"
    echo "   Stop app:      docker stop plc-app"
    echo "   Restart app:   docker restart plc-app"
    echo ""
    echo "🎉 Everything is running automatically!"

else
    log_error "❌ Failed to start PLC application"
    log_info "Check logs: docker logs plc-app"
    exit 1
fi