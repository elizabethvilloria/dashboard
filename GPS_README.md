# E-Trike GPS Tracking System

This system provides real-time GPS tracking for E-Trike vehicles using the VK-162 USB GPS receiver.

## Features

- **Real-time Vehicle Tracking** - Live map view of all E-Trike vehicles
- **GPS Data Collection** - Automatic GPS data collection from VK-162 USB receiver
- **Filtering System** - Filter by TODA, E-Trike, or Pi device
- **Statistics Dashboard** - Active vehicles, distance traveled, speed, passengers
- **Interactive Map** - Built with Leaflet.js for smooth performance

## Hardware Requirements

- **VK-162 USB GPS Receiver** - GPS module with antenna and USB interface
- **Raspberry Pi** - For running the GPS data collection script
- **USB Connection** - Connect VK-162 to Pi via USB

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements_gps.txt
```

### 2. Connect VK-162 GPS Receiver

1. Connect the VK-162 USB GPS receiver to your Raspberry Pi
2. The device should appear as `/dev/ttyUSB0` (or similar)
3. Verify connection: `ls /dev/ttyUSB*`

### 3. Test GPS Connection

```bash
# Test if GPS is working
python -c "
import serial
import pynmea2
ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
for i in range(10):
    line = ser.readline().decode('ascii', errors='ignore')
    if line.startswith('$GPRMC'):
        msg = pynmea2.parse(line)
        print(f'Lat: {msg.latitude}, Lon: {msg.longitude}')
        break
"
```

## Usage

### 1. Start the Dashboard

```bash
python dashboard.py
```

### 2. Register Pi Device

1. Go to the dashboard
2. Navigate to "Pi Registration"
3. Register your Pi device with TODA and E-Trike information

### 3. Start GPS Data Collection

```bash
# Basic usage
python gps_sender.py pi001

# With custom dashboard URL
python gps_sender.py pi001 http://192.168.1.100:5001

# With custom serial port
python gps_sender.py pi001 http://localhost:5001 /dev/ttyUSB1
```

### 4. View GPS Map

1. Open the dashboard
2. Click "GPS Map" in the sidebar
3. View real-time vehicle tracking

## API Endpoints

### GPS Data Collection

**POST** `/gps-data`
```json
{
    "pi_id": "pi001",
    "latitude": 14.5995,
    "longitude": 120.9842,
    "speed": 25.5,
    "heading": 45.0,
    "timestamp": 1705334400
}
```

### Vehicle Locations

**GET** `/vehicle-locations`
```json
{
    "vehicles": [
        {
            "id": "etrike-001",
            "name": "E-Trike 00001",
            "lat": 14.5995,
            "lng": 120.9842,
            "speed": 25,
            "heading": 45,
            "status": "active",
            "passengers": 2,
            "toda": "bltmpc",
            "pi": "pi001",
            "last_update": "2024-01-15T10:30:00"
        }
    ]
}
```

## Configuration

### GPS Receiver Settings

- **Baud Rate**: 9600
- **Data Format**: NMEA 0183
- **Update Rate**: 1Hz (1 update per second)
- **Accuracy**: ~3-5 meters

### Dashboard Settings

- **Update Interval**: 5 seconds
- **Data Retention**: Last 1000 GPS entries
- **Status Check**: 60 seconds (vehicles offline after 1 minute)

## Troubleshooting

### GPS Not Working

1. Check USB connection: `ls /dev/ttyUSB*`
2. Verify permissions: `sudo chmod 666 /dev/ttyUSB0`
3. Test with: `cat /dev/ttyUSB0`

### No Data on Map

1. Check Pi registration in dashboard
2. Verify GPS data is being sent: Check dashboard logs
3. Ensure GPS has satellite fix (outdoor testing recommended)

### Permission Denied

```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
# Logout and login again
```

## File Structure

```
dashboard/
├── templates/
│   └── gps_map.html          # GPS map interface
├── dashboard.py              # Main dashboard with GPS routes
├── gps_sender.py             # GPS data collection script
├── requirements_gps.txt      # GPS dependencies
└── logs/
    └── gps_data.json         # GPS data storage
```

## Security Notes

- GPS data is stored locally in JSON files
- No external GPS services used
- All data remains on your local network
- Consider HTTPS for production deployment

## Support

For issues or questions:
1. Check the dashboard logs
2. Verify GPS receiver connection
3. Test with mock data first
4. Check network connectivity between Pi and dashboard
