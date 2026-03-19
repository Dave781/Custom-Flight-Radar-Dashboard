#!/bin/bash
# Install and run the ADS-B Flight Dashboard on Raspberry Pi

set -e

echo "================================="
echo "  ADS-B Flight Dashboard Setup"
echo "================================="

# Install Python dependencies
echo ""
echo "[1/2] Installing Python dependencies..."
pip3 install -r requirements.txt

# Create systemd service for auto-start
echo ""
echo "[2/2] Creating systemd service..."

sudo tee /etc/systemd/system/flight-dashboard.service > /dev/null << EOF
[Unit]
Description=ADS-B Flight Dashboard
After=network.target dump1090-fa.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/python3 $(pwd)/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable flight-dashboard
sudo systemctl start flight-dashboard

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
