#!/bin/bash
# Fully Automated PLC Project Deployment
# Run this on your Debian server - everything happens automatically!

set -e

echo "🤖 PLC Project - Fully Automated Deployment"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    log_error "This script should not be run as root. Please run as a regular user with sudo access."
    exit 1
fi

# Function to check command availability
check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is not installed. Installing..."
        sudo apt-get update
        sudo apt-get install -y $1
    else
        log_info "$1 is available"
    fi
}

# Install required system packages
log_info "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y curl wget gnupg lsb-release software-properties-common

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    log_info "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    log_warn "Docker installed. You may need to log out and back in for group changes to take effect."
else
    log_info "Docker is already installed"
fi

# Install Docker Compose if not present
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_info "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    log_info "Docker Compose is available"
fi

# Create project directory if it doesn't exist
if [ ! -d "PLC_Project" ]; then
    log_info "Creating project directory..."
    mkdir -p PLC_Project
    cd PLC_Project
else
    log_info "Project directory exists, updating..."
    cd PLC_Project
    # Backup current .env if it exists
    if [ -f ".env" ]; then
        cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
    fi
fi

# Clone or update repository
if [ ! -d ".git" ]; then
    log_info "Cloning repository..."
    # This would be replaced with actual repo URL
    log_error "Please clone your repository first or provide the repository URL"
    log_info "Example: git clone https://github.com/yourusername/PLC_Project.git"
    exit 1
else
    log_info "Updating repository..."
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || log_warn "Could not update repository"
fi

# Create .env file with defaults if it doesn't exist
if [ ! -f ".env" ]; then
    log_info "Creating environment configuration..."
    cp .env.example .env 2>/dev/null || log_warn ".env.example not found, using defaults"
fi

# You can add additional configuration templates, secrets management etc here.
# E.g. configure certbot path, SSL, or custom feature flags:
# if [ ! -f "ssl.conf" ]; then ...

# Stop any existing containers
log_info "Stopping existing containers..."
docker-compose down 2>/dev/null || docker compose down 2>/dev/null || true

# Build and start the application
log_info "Building and starting PLC application..."
if docker compose version &> /dev/null; then
    docker compose up -d --build
else
    docker-compose up -d --build
fi

# Wait for services to start
log_info "Waiting for services to initialize..."
sleep 30

# Check if services are running
log_info "Checking service status..."
if docker compose version &> /dev/null; then
    docker compose ps
else
    docker-compose ps
fi

# Test the application
log_info "Testing application health..."
if curl -f http://localhost/health/ &>/dev/null; then
    log_info "✅ Application is healthy!"
else
    log_warn "⚠️  Health check failed, but services may still be starting..."
fi

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="localhost"
fi

echo ""
echo "🎉 DEPLOYMENT COMPLETE!"
echo "======================"
echo ""
echo "🌐 Your PLC application is running at:"
echo "   http://$SERVER_IP"
echo "   http://localhost"
echo ""
echo "📱 Mobile apps will be available in CI/CD artifacts"
echo ""
echo "🔧 Management commands:"
echo "   View logs: docker-compose logs -f"
echo "   Stop app:  docker-compose down"
echo "   Restart:   docker-compose restart"
echo ""
echo "📊 Monitor:"
echo "   Health:   http://$SERVER_IP/health/"
echo "   Admin:    http://$SERVER_IP/admin/"
echo ""
echo "⚠️  Remember to:"
echo "   - Change default passwords in .env"
echo "   - Set up SSL/HTTPS for production"
echo "   - Configure firewall rules"
echo ""
echo "🚀 Happy deploying!"