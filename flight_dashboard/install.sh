#!/bin/bash
# Install and run the ADS-B Flight Dashboard on Raspberry Pi

set -e
cd "$(dirname "$0")"

echo "================================="
echo "  ADS-B Flight Dashboard Setup"
echo "================================="

# Install Python dependencies into a virtualenv
echo ""
echo "[1/3] Installing Python dependencies..."
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Download the map for the antenna's area (needs HOME_LAT / HOME_LON in .env)
echo ""
echo "[2/3] Downloading the map..."
if [ -f data/map.pmtiles ]; then
    echo "data/map.pmtiles already exists, skipping. Run download_map.py to refresh it."
elif [ -f .env ]; then
    venv/bin/python3 download_map.py || echo "Map download failed. Run venv/bin/python3 download_map.py later."
else
    echo "No .env yet. Copy .env.example to .env, set HOME_LAT and HOME_LON, then run:"
    echo "  venv/bin/python3 download_map.py"
fi

# Create systemd service for auto-start
echo ""
echo "[3/3] Creating systemd service..."

sudo tee /etc/systemd/system/flight-dashboard.service > /dev/null << EOF2
[Unit]
Description=ADS-B Flight Dashboard
After=network.target fr24feed.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python3 $(pwd)/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF2

sudo systemctl daemon-reload
sudo systemctl enable flight-dashboard
sudo systemctl restart flight-dashboard

echo ""
echo "================================="
echo "  Setup Complete!"
echo "================================="
echo ""
echo "Dashboard running at: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "Manage with:"
echo "  sudo systemctl status flight-dashboard"
echo "  sudo systemctl restart flight-dashboard"
echo "  sudo systemctl stop flight-dashboard"
echo ""
