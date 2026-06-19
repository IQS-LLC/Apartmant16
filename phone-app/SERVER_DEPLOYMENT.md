# PLC Project - Server Deployment Guide

## Overview

This project is designed for easy deployment on Debian-based Linux servers with 24/7 uptime. The entire stack runs in Docker containers with Nginx reverse proxy and PostgreSQL database.

## Quick Deployment

### Prerequisites

- Debian/Ubuntu server with sudo access
- Git
- Internet connection

### One-Command Deployment

```bash
# Clone repository
git clone <your-repo-url>
cd PLC_Project

# Make deploy script executable (if not already)
chmod +x deploy.sh

# Run deployment
./deploy.sh
```

That's it! Your application will be available at `http://your-server-ip`

## Architecture

```
Internet → Nginx (Port 80/443) → Gunicorn → Django → PostgreSQL
                                      ↓
                                Flutter Apps (Mobile)
```

### Components

- **Django**: Backend API with Gunicorn WSGI server
- **PostgreSQL**: Production database
- **Nginx**: Reverse proxy and static file serving
- **Flutter**: Cross-platform mobile apps (Android/iOS)

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
nano .env
```

Required settings:
- `SECRET_KEY`: Django secret key
- `DB_PASSWORD`: PostgreSQL password
- `ALLOWED_HOSTS`: Your domain/IP

### SSL/HTTPS (Recommended)

1. Get SSL certificate:
```bash
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com
```

2. Update Nginx config to use SSL certificates

3. Mount certificates in `docker-compose.prod.yml`

## Mobile Apps

### Building Apps

**Android APK:**
```bash
cd flutter_application_plc
flutter build apk --release
# Output: build/app/outputs/flutter-apk/app-release.apk
```

**iOS IPA:**
```bash
cd flutter_application_plc
flutter build ios --release
# Output: build/ios/iphoneos/Runner.app
```

### Installing on Devices

**Android:**
- Transfer APK to device
- Enable "Install from unknown sources"
- Install APK

**iOS:**
- Use TestFlight for distribution
- Or use `flutter install` for development devices

## Management Commands

```bash
# View all logs
docker-compose logs -f

# View Django logs only
docker-compose logs -f django

# Restart all services
docker-compose restart

# Update deployment
git pull
docker-compose down
docker-compose up -d --build

# Access Django container
docker-compose exec django bash

# Run Django management commands
docker-compose exec django python manage.py shell
docker-compose exec django python manage.py migrate

# Backup database
docker-compose exec db pg_dump -U plc_user plc_db > backup_$(date +%Y%m%d).sql

# Monitor resources
docker stats
```

## Monitoring

- **Application Health:** `http://your-server/health/`
- **Django Admin:** `http://your-server/admin/`
- **API Endpoints:** `http://your-server/api/`

## Troubleshooting

### Common Issues

**Port 80 already in use:**
```bash
sudo netstat -tulpn | grep :80
sudo systemctl stop apache2  # or nginx if running
```

**Database connection failed:**
```bash
docker-compose logs db
docker-compose exec django python manage.py dbshell
```

**Static files not loading:**
```bash
docker-compose exec django python manage.py collectstatic --noinput
docker-compose restart nginx
```

### Logs and Debugging

```bash
# All logs
docker-compose logs

# Follow logs
docker-compose logs -f

# Django specific logs
docker-compose logs django

# Check container status
docker-compose ps
```

## Security Considerations

- Change default passwords in `.env`
- Use strong `SECRET_KEY`
- Enable HTTPS in production
- Regularly update Docker images
- Monitor logs for suspicious activity

## Backup Strategy

### Database Backup

```bash
# Daily backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker-compose exec db pg_dump -U plc_user plc_db > /backups/db_backup_$DATE.sql
find /backups -name "db_backup_*.sql" -mtime +7 -delete  # Keep 7 days
```

### Full Backup

```bash
# Stop services
docker-compose down

# Backup volumes
docker run --rm -v plc_project_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/backup_$(date +%Y%m%d).tar.gz -C / data

# Start services
docker-compose up -d
```

## Scaling

For high traffic, consider:

1. **Load Balancing:** Multiple Django containers
2. **Redis Cache:** Add Redis for session/cache storage
3. **CDN:** Use CloudFlare or similar for static assets
4. **Database Replication:** PostgreSQL streaming replication

## Support

- Check logs: `docker-compose logs -f`
- Django debug: `docker-compose exec django python manage.py check`
- Flutter issues: Check device logs and API connectivity