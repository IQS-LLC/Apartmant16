# PLC Project - Fully Automated System

## 🎯 Mission
**Zero-touch deployment and operation.** Everything runs automatically from the moment you pull the code.

## 🚀 One-Command Deployment

```bash
# On any Debian/Ubuntu server
git clone <your-repo>
cd PLC_Project
./auto_deploy.sh
```

**That's literally it.** The entire system deploys and runs automatically.

## 🤖 What Happens Automatically

### Server Setup
- Installs Docker & dependencies
- Builds production container with all services
- Configures PostgreSQL, Django, Nginx
- Starts everything with process management
- Sets up health checks and monitoring

### Mobile Apps
- CI/CD automatically builds Android APK
- iOS IPA built on macOS runners
- Artifacts uploaded for instant download
- Apps install and connect automatically

### Build Flow for Connected App
- `flutter pub get` (dependencies)
- `flutter test` (quality checks)
- `flutter build apk --release --dart-define=API_BASE_URL=https://your-server.com`
- `flutter build ios --release --no-codesign --dart-define=API_BASE_URL=https://your-server.com`

In app startup (`main.dart`):
- `kBaseUrl` is populated from `API_BASE_URL`
- fallback `10.0.2.2` is used for emulator/local
- first call `getState()` is used for quick connection check
- failure path shows instructions and retry

Use these in CI/CD finalized artifact builds, then install to devices.

### Operations
- 24/7 uptime with auto-restart
- Self-healing with supervisord
- Automatic database migrations
- Static file collection
- Log rotation and monitoring

## 📱 Mobile Installation

**Android:**
```bash
# Download from CI/CD artifacts
# Transfer APK to device
# Install (allow unknown sources)
# App works immediately
```

**iOS:**
```bash
# Download from CI/CD artifacts
# Install via TestFlight or direct
# App works immediately
```

## 🏗️ Architecture

```
Single Production Container
├── PostgreSQL (Auto-configured DB)
├── Django + Gunicorn (API Backend)
├── Nginx (Web Server & Proxy)
└── Supervisor (Process Management)
```

## 🔧 Management

```bash
# View logs
docker logs -f plc-app

# Restart
docker restart plc-app

# Update
git pull && docker build -f Dockerfile.single -t plc-project:latest . && docker restart plc-app

# Access container
docker exec -it plc-app bash
```

## 🌐 Access Points

- **Web App:** `http://your-server-ip`
- **API:** `http://your-server-ip/api/`
- **Health:** `http://your-server-ip/health/`
- **Admin:** `http://your-server-ip/admin/`

## 🔒 Security

- Containerized isolation
- Minimal attack surface
- Configurable environment variables
- SSL/HTTPS ready

## 📊 Monitoring

- Built-in health checks
- Automatic log rotation
- Resource monitoring
- Process supervision

## 🎉 Result

**From zero to production in one command.** No configuration, no setup, no manual steps. Just deploy and use.

The system handles everything automatically - from database setup to mobile app builds to 24/7 operation. Welcome to the future of deployment! 🚀