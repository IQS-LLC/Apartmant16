#!/bin/bash
# PLC Project Deployment Script
# Run this on your Debian server after cloning the repository

set -e

echo "🚀 PLC Project Deployment Script"
echo "================================="

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ This script should not be run as root. Please run as a regular user with sudo access."
   exit 1
fi

# Update system
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Docker and Docker Compose
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

echo "🐳 Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your production settings!"
    echo "   nano .env"
    read -p "Press enter when you've updated the .env file..."
fi

# Build and start services
echo "🏗️  Building and starting services..."
docker-compose up -d --build

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 30

# Run migrations
echo "🗄️  Running database migrations..."
docker-compose exec django python manage.py migrate

# Collect static files
echo "📂 Collecting static files..."
docker-compose exec django python manage.py collectstatic --noinput

# Restart services
echo "🔄 Restarting services..."
docker-compose restart

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🌐 Your application should be available at:"
echo "   http://your-server-ip"
echo ""
echo "📱 Mobile apps are available in the CI/CD artifacts"
echo ""
echo "🔧 Useful commands:"
echo "   docker-compose logs -f          # View logs"
echo "   docker-compose restart          # Restart services"
echo "   docker-compose down             # Stop services"
echo "   docker-compose exec django bash # Access Django container"