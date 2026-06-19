#!/bin/bash
# Automated Mobile App Builder
# Builds Android APK and iOS IPA automatically

set -e

echo "📱 PLC Project - Mobile App Builder"
echo "==================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# Check if Flutter is installed
if ! command -v flutter &> /dev/null; then
    log_error "Flutter is not installed. Installing Flutter..."
    git clone https://github.com/flutter/flutter.git -b stable /opt/flutter
    export PATH="$PATH:/opt/flutter/bin"
    flutter doctor --android-licenses
else
    log_info "Flutter is available"
fi

# Navigate to Flutter project
cd flutter_application_plc

# Get dependencies
log_info "Installing Flutter dependencies..."
flutter pub get

# Run tests
log_info "Running Flutter tests..."
flutter test

# Build Android APK
log_info "Building Android APK..."
flutter build apk --release

# Check if iOS build is possible (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    log_info "Building iOS IPA..."
    flutter build ios --release --no-codesign
else
    log_warn "iOS build skipped (requires macOS)"
fi

# Create build artifacts directory
mkdir -p ../build_artifacts

# Copy Android APK
if [ -f "build/app/outputs/flutter-apk/app-release.apk" ]; then
    cp build/app/outputs/flutter-apk/app-release.apk ../build_artifacts/plc_app.apk
    log_info "✅ Android APK built: build_artifacts/plc_app.apk"
else
    log_error "❌ Android APK build failed"
fi

# Copy iOS IPA if built
if [[ "$OSTYPE" == "darwin"* ]] && [ -d "build/ios/iphoneos/Runner.app" ]; then
    cp -r build/ios/iphoneos/Runner.app ../build_artifacts/
    log_info "✅ iOS app built: build_artifacts/Runner.app"
fi

# Generate QR codes for easy mobile installation
if command -v qrencode &> /dev/null; then
    log_info "Generating QR codes for mobile installation..."
    SERVER_IP=$(hostname -I | awk '{print $1}')
    if [ ! -z "$SERVER_IP" ]; then
        echo "http://$SERVER_IP" | qrencode -o ../build_artifacts/server_qr.png
        log_info "📱 Server QR code: build_artifacts/server_qr.png"
    fi
fi

log_info "🎉 Mobile app build complete!"
log_info "APK available at: build_artifacts/plc_app.apk"
if [[ "$OSTYPE" == "darwin"* ]]; then
    log_info "iOS app available at: build_artifacts/Runner.app"
fi