# 🚀 PLC Light Control Demo - Quick Start Guide

## Server Deployment (Debian Linux)

### One-Command Server Setup

**Deploy to production server:**

```bash
# On your Debian server
git clone <your-repo-url>
cd PLC_Project
chmod +x deploy.sh
./deploy.sh
```

**That's it!** Your app will be running at `http://your-server-ip`

### What Gets Deployed

- ✅ **Django backend** with Gunicorn WSGI server
- ✅ **PostgreSQL database** with persistent data
- ✅ **Nginx reverse proxy** with SSL-ready config
- ✅ **Docker containers** for easy management
- ✅ **24/7 uptime** with auto-restart

### Mobile Apps

**Android APK:** Available in CI/CD artifacts or build locally:
```bash
cd flutter_application_plc
flutter build apk --release
# APK: build/app/outputs/flutter-apk/app-release.apk
```

**iOS IPA:** Available in CI/CD artifacts or build locally:
```bash
cd flutter_application_plc
flutter build ios --release
# IPA: build/ios/iphoneos/Runner.app
```

**Install on devices:**
- **Android:** Transfer APK to phone and install
- **iOS:** Use TestFlight or direct installation

---

## Development Setup

### Local Development

Everything runs with **one interactive script**. Choose your scenario:

---

## 📱 Scenario 1: Android Emulator (Local Development)

**Best for:** Testing on your PC with Android emulator

```powershell
cd c:\Users\Automation\PycharmProjects\PLC_Project
.\start_project.ps1 -Mode local
```

Or run interactively:

```powershell
.\start_project.ps1
```

**What happens:**
- ✅ Detects if emulator is running
- ✅ Django backend starts on appropriate endpoint
- ✅ Flutter app starts on Android emulator
- ✅ App automatically connects to correct API endpoint

---

## 📡 Scenario 2: Real Phone on Same WiFi

**Best for:** Testing on a real phone on your home/office network

```powershell
cd c:\Users\Automation\PycharmProjects\PLC_Project
.\start_project.ps1 -Mode lan
```

**What happens:**
- ✅ Detects your PC's local IP automatically
- ✅ Django backend starts on `0.0.0.0:8000`
- ✅ Flutter app starts on your phone
- ✅ App connects to your PC's IP

---

## 🐳 Scenario 3: Docker Mode

**Best for:** Containerized development

```powershell
cd c:\Users\Automation\PycharmProjects\PLC_Project
.\start_project.ps1 -Mode docker -UseDocker
```

**What happens:**
- ✅ Builds and runs Django in Docker container
- ✅ Flutter runs locally
- ✅ Isolated environment

---

## ⚙️ Advanced Options

```powershell
# Custom IP
.\start_project.ps1 -Mode custom -IP "192.168.1.100"

# Skip Flutter, just start Django
.\start_project.ps1 -Mode lan -SkipFlutter

# Debug mode (runs in foreground)
.\start_project.ps1 -Mode local -Debug
```

---

## 🛠️ Development Commands

```bash
# Run Django tests
python manage.py test

# Run Flutter tests
cd flutter_application_plc && flutter test

# Build with Docker
docker compose build

# Run with Docker
docker compose up

# Format code
make format

# Lint code
make lint
```

---

## Server Management

### Production Commands

```bash
# View logs
docker-compose logs -f

# Restart services
docker-compose restart

# Update deployment
git pull && docker-compose up -d --build

# Backup database
docker-compose exec db pg_dump -U plc_user plc_db > backup.sql

# Access Django shell
docker-compose exec django python manage.py shell

# Run migrations
docker-compose exec django python manage.py migrate
```

### Monitoring

- **Health check:** `http://your-server/health/`
- **Logs:** `docker-compose logs -f django`
- **Resource usage:** `docker stats`

### SSL Setup (Optional)

1. Get SSL certificate (Let's Encrypt recommended)
2. Update `nginx/nginx.conf` with SSL config
3. Mount certificates in `docker-compose.prod.yml`

---

## CI/CD Pipeline

### Automated Builds

- **Django tests** run on every push
- **Flutter tests** run on Ubuntu and macOS
- **Android APK** built and uploaded as artifact
- **iOS app** built and uploaded as artifact
- **Docker images** built for deployment

### Mobile Deployment

**Using Fastlane:**

```bash
# Android
cd flutter_application_plc/android
fastlane android build_and_deploy

# iOS
cd flutter_application_plc/ios
fastlane ios build_and_deploy
```

**Manual deployment:**
- Download artifacts from GitHub Actions
- Install APKs/IPAs on test devices
- Use Firebase App Distribution for beta testing

## 📋 Prerequisites

- Python 3.11+ with virtual environment
- Flutter SDK
- Android Studio (for emulator)
- Optional: Docker Desktop

---

## 🔧 Troubleshooting

- **Emulator not detected:** Start Android emulator first
- **Network issues:** Check firewall settings
- **Port conflicts:** Change port in settings.py
- **Dependencies:** Run `pip install -r requirements.txt` and `flutter pub get`

### Start Flutter only:
```bash
cd c:\Users\Automation\PycharmProjects\PLC_Project\flutter_application_plc
flutter pub get
flutter run
```

### List available devices:
```bash
flutter devices
```

### Run on specific device:
```bash
flutter run -d emulator-5554
```

---

## 📋 Troubleshooting

### "Cannot reach server"
- For **emulator**: Phone uses `10.0.2.2`, PC uses `127.0.0.1` ✅ (handled by script)
- For **real phone**: Both must be on **same WiFi** ✅ (handled by script)
- For **internet**: Backend must have **public IP/domain** ✅ (set in config.env)

### Django doesn't start
- Check if port 8000 is blocked: `netstat -ano | findstr :8000`
- Change `DJANGO_PORT` in `config.env` if needed
- Kill old process: `taskkill /F /IM python.exe`

### Flutter can't find device
- Start Android emulator first in Android Studio
- Run `flutter devices` to see list
- Set `FLUTTER_DEVICE` in `config.env` if needed

### Port 8000 already in use
- Edit `config.env` and change `DJANGO_PORT` to `8001`, etc.
- Update `API_ENDPOINT` accordingly

---

## 📚 How It All Works Together

```
┌─────────────────────────────────────────┐
│         Your PC (Windows)               │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────┐    ┌──────────────┐   │
│  │  Django     │    │  Flutter App │   │
│  │  Backend    │←───→  (emulator   │   │
│  │  :8000      │    │   or real)   │   │
│  │             │    │              │   │
│  │  PLC Driver │    │  UI Controls │   │
│  │  (mock/real)│    │  Status/Log  │   │
│  └─────────────┘    └──────────────┘   │
│                                         │
└─────────────────────────────────────────┘
         ↓ (same WiFi or 10.0.2.2)
         
    ┌──────────────────┐
    │  Android Phone   │
    │  (real device)   │
    │  or Emulator     │
    └──────────────────┘
```

---

## 🎯 Next Steps

1. **For emulator testing:** Run `start_local.bat`
2. **For phone testing:** Run `start_lan.bat`
3. **For production:** Update `config.env` and use `start_demo.ps1`
4. **For real PLC:** Currently running mock mode (fallback when real PLC unavailable)
5. **To control from anywhere:** Deploy backend to cloud, update API endpoint

---

## 🚨 Important for Production

When building for real deployment:

1. **Backend URL must be accessible** from target network
2. **CORS is enabled** in Django (already set to `*` for dev)
3. **SSL/HTTPS recommended** for public internet (update `API_ENDPOINT`)
4. **API port must not be firewalled** from client devices
5. **Real PLC must be connected** to your CX9180 on same network as backend

---

**Easy demo ready?** Just run:
```bash
.\start_local.bat
```

Everything else is automatic! 🎉
