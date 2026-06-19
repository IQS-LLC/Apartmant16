# PLC Light Control Demo

A complete Flutter + Django + PLC automation demo for controlling lights via mobile/web interface.

## Architecture

- **Flutter App**: Cross-platform mobile and web interface for light control
- **Django Backend**: REST API server handling PLC communication
- **PLC Integration**: Beckhoff TwinCAT 3 PLC with ADS protocol (with mock mode for demo)

## Features

- Real-time brightness control with circular dimmer
- Scene presets (Off, Night, Warm, Work, Full)
- Fade duration settings
- System status monitoring
- Activity logging
- Responsive design for mobile and web

## Setup & Running

### Backend (Django)

1. Install dependencies:
   ```bash
   pip install django django-cors-headers pyads
   ```

2. Run migrations:
   ```bash
   python manage.py migrate
   ```

3. Start server:
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

The backend includes mock PLC mode for demo purposes when real PLC is unavailable.

### Frontend (Flutter)

1. Ensure Flutter is installed and configured

2. Update API endpoint in `lib/main.dart`:
   ```dart
   const String kBaseUrl = 'http://YOUR_SERVER_IP:8000';
   ```

3. Run the app:
   ```bash
   flutter run
   ```

## API Endpoints

- `GET /plc/state/` - Get current PLC state
- `POST /plc/brightness/` - Set brightness (0-100)
- `POST /plc/fade/` - Set fade duration
- `GET /plc/` - Health check

## PLC Variables

The system expects these TwinCAT GVL variables:
- `GVL.nDimLevel` (BYTE): Brightness level 0-254
- `GVL.nFadeTime` (USINT): Fade time index
- `GVL.bLightTrigger` (BOOL): Command trigger
- `GVL.nActualLevel` (BYTE): Current level
- `GVL.bSystemReady` (BOOL): System status
- `GVL.bLightError` (BOOL): Error flag
- `GVL.bSwitchChannel1/2` (BOOL): Button states

## Demo Mode

When real PLC is not available, the system automatically switches to mock mode with simulated responses and occasional button press events.