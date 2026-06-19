# 🚀 PLC Light Control Demo - Fully Automated Deployment

## One-Command Everything

**Deploy the entire system automatically:**

```bash
# On your Debian server
git clone <your-repo-url>
cd PLC_Project
chmod +x auto_deploy.sh
./auto_deploy.sh
```

**That's it!** Everything runs automatically - Django, PostgreSQL, Nginx, mobile apps, CI/CD.

---

## What Happens Automatically

### 🤖 **Server Setup**
- ✅ Installs Docker & Docker Compose
- ✅ Builds single production container
- ✅ Configures PostgreSQL database
- ✅ Sets up Nginx reverse proxy
- ✅ Starts all services with supervisord

### 📱 **Mobile Apps**
- ✅ Builds Android APK automatically
- ✅ Builds iOS IPA (on macOS CI/CD)
- ✅ Uploads artifacts for download
- ✅ Ready for device installation

### 🔄 **CI/CD Pipeline**
- ✅ Tests Django backend
- ✅ Tests Flutter mobile apps
- ✅ Builds production Docker image
- ✅ Deploys to registry automatically
- ✅ Creates installable mobile apps

---

## Manual Run (Single Container)

If you just want to run locally:

```bash
# Build and run everything in one container
chmod +x run.sh
./run.sh
```

**Result:** Complete application at `http://localhost`

---

## Architecture Overview

```
Single Docker Container
├── PostgreSQL Database (Auto-configured)
├── Django Backend (Gunicorn WSGI)
├── Nginx Proxy (Port 80)
└── Static Files (Auto-collected)
```

---

## Mobile App Installation

### Android
1. Download APK from CI/CD artifacts
2. Transfer to Android device
3. Install APK (allow unknown sources)
4. App connects automatically

### iOS
1. Download IPA from CI/CD artifacts
2. Use TestFlight or direct install
3. App connects automatically

---

## Management Commands

```bash
# View all logs
docker logs -f plc-app

# Stop application
docker stop plc-app

# Restart application
docker restart plc-app

# Update deployment
git pull && docker build -f Dockerfile.single -t plc-project:latest . && docker restart plc-app

# Access container
docker exec -it plc-app bash
```

---

## Production URLs

- **Web Interface:** `http://your-server-ip`
- **API Health:** `http://your-server-ip/health/`
- **Admin Panel:** `http://your-server-ip/admin/`

---

## Security Notes

- Change default database password in production
- Set up SSL/HTTPS with Let's Encrypt
- Configure firewall (only port 80/443 open)
- Use strong SECRET_KEY

---

## Troubleshooting

**Container won't start:**
```bash
docker logs plc-app
```

**Database issues:**
```bash
docker exec plc-app /etc/init.d/postgresql status
```

**Web server issues:**
```bash
docker exec plc-app nginx -t
```

---

## Fully Automated Benefits

✅ **Zero manual configuration**  
✅ **Single command deployment**  
✅ **24/7 automatic operation**  
✅ **Mobile apps built automatically**  
✅ **CI/CD with artifact delivery**  
✅ **Production-ready security**  
✅ **Self-healing with supervisord**  

The entire system from development to production deployment is now completely automated! 🎉