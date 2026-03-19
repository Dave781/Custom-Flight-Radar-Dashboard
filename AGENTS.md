# AGENTS.md — AI Agent Setup Guide

This file helps AI agents (Claude, Copilot, etc.) understand, configure, and extend this project.

## What This Project Does

A real-time ADS-B flight tracking dashboard running on a Raspberry Pi. It reads aircraft data from a local RTL-SDR dongle via the FlightRadar24 feeder (dump1090), enriches it with an aircraft database, and serves a dark radar-style web UI on port 8080. Includes a live radar map overlay, emergency squawk alerts, auto-dimming, bearing indicators, and aircraft classification (MIL/HEAVY).

## Hardware Requirements

- Raspberry Pi (any model with USB port; Pi 3B+ or later recommended)
- RTL-SDR USB dongle (RTL2832U-based, e.g. FlightAware Pro Stick, NooElec NESDR)
- Antenna (1090 MHz, e.g. a simple monopole or dedicated ADS-B antenna)
- Optional: second Pi with 8" touchscreen for kiosk display

## Software Stack

```
RTL-SDR dongle
    → fr24feed (FlightRadar24 feeder, manages dump1090)
        → /run/dump1090/aircraft.json  (updated every 1 second)
            → flight_dashboard/app.py  (Flask, reads JSON, enriches data)
                → http://<pi-ip>:8080  (web dashboard, auto-refreshes every 2s)
                    → Kiosk Pi (Chromium fullscreen on touchscreen)
```

## Key Files

| File | Purpose |
|------|---------|
| `flight_dashboard/app.py` | Flask backend — reads aircraft.json, enriches with DB, classifies aircraft, serves API |
| `flight_dashboard/templates/index.html` | Single-page frontend — all CSS, HTML, JS in one file including radar map, coastline, alerts |
| `flight_dashboard/download_db.py` | Downloads aircraft DB from OpenSky Network (~500MB CSV → JSON) |
| `flight_dashboard/requirements.txt` | Python dependencies (just Flask) |
| `flight_dashboard/install.sh` | Install script (sets up systemd service) |
| `flight_dashboard/data/aircraft_db.json` | Generated aircraft DB (gitignored, run download_db.py) |
| `/etc/fr24feed.ini` | FR24 feeder config (on the Pi, not in repo) |
| `/etc/systemd/system/flight-dashboard.service` | Systemd service definition (on the Pi, not in repo) |

## Configurable Values

All can be set via environment variables or edited directly in `app.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_TITLE` | `Dave's ADS-B Radar` | Title shown in browser tab and header |
| `HOME_LAT` | `47.650923` | Antenna latitude (hardcoded in app.py) |
| `HOME_LON` | `-122.346385` | Antenna longitude (hardcoded in app.py) |
| `SEEN_THRESHOLD` | `120` | Max seconds since last contact to show aircraft |
| `PORT` | `8080` | Web server port |
| `DEMO_MODE` | `false` | Use built-in sample data instead of live dump1090 |

To change `HOME_LAT`/`HOME_LON`, edit them directly in `app.py` — they are not env-var controlled.

## Location-Specific Customization

When setting this up for a new location, three things must be updated:

### 1. Antenna coordinates in `app.py`
```python
HOME_LAT = your_latitude
HOME_LON = your_longitude
```

### 2. Coastline data in `templates/index.html`
Find the `COASTLINE_POINTS` JavaScript array. Replace with local coastal coordinates as `[lat, lon]` pairs. Use `null` to separate disconnected segments. Source coordinates from OpenStreetMap. Only include points within radar range (default 25 mi).

### 3. Radar range (optional) in `templates/index.html`
```javascript
const RANGE_RINGS_MI = [5, 10, 20];  // ring distances
const MAX_RANGE_MI = 25;              // outer boundary
```

## Aircraft Classification

The backend (`app.py`) classifies aircraft into categories returned in `aircraft_class`:

| Class | Detection Method |
|-------|-----------------|
| `military` | US military ICAO hex (AE prefix, ADF000–ADFFFF), UK military (43 prefix), Australian RAAF (7CF800–7CFFFE) |
| `heavy` | Wide-body type codes: B74*, B77*, B78*, A33*, A34*, A35*, A38*, B76* |
| `emergency` | Squawk codes 7500, 7600, 7700 |
| (none) | Standard civil aircraft |

The frontend applies gold styling for MIL, cyan for HEAVY, and red for emergency aircraft in both the contacts list and featured panel.

## Frontend Features

| Feature | Implementation |
|---------|---------------|
| Radar map | Canvas-based, modal overlay via ⬤ RADAR button. Auto-closes after 15s of no interaction |
| Coastline | `COASTLINE_POINTS` array drawn as green polyline on radar canvas |
| Bearing | Calculated from antenna lat/lon to aircraft position, shown as degrees + cardinal (e.g. "148° SE") |
| Emergency alerts | Monitors squawk codes, shows dismissable banner with color coding per squawk type |
| Auto-dim | NOAA solar altitude calculation for sunrise/sunset. Dims to 40% at night. Manual override via ☀/☾ toggle |
| Reconnection | Graceful handling of brief API drops — shows "Reconnecting..." without losing last known data |

## Setup Steps (Fresh Pi)

1. **Install FR24 feeder** — follow https://www.flightradar24.com/share-your-data
   - During setup, provide your lat/lon and altitude
   - Note your sharing key (stored in `/etc/fr24feed.ini` as `fr24key=`)

2. **Configure dump1090 JSON output** — edit `/etc/fr24feed.ini`:
   ```ini
   procargs="--write-json /run/dump1090 --write-json-every 1"
   ```
   Then: `sudo systemctl restart fr24feed`

3. **Fix permissions**:
   ```bash
   sudo chown -R fr24:fr24 /run/dump1090/
   sudo chmod 755 /run/dump1090/
   ```

4. **Clone repo and set up Python**:
   ```bash
   git clone https://github.com/Dave781/Custom-Flight-Radar-Dashboard.git
   cd Custom-Flight-Radar-Dashboard/flight_dashboard
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/python3 download_db.py  # downloads aircraft database (~5 min)
   ```

5. **Set your antenna location** — edit `flight_dashboard/app.py`:
   ```python
   HOME_LAT = 47.650923   # your latitude
   HOME_LON = -122.346385  # your longitude
   ```

6. **Update coastline** — edit `flight_dashboard/templates/index.html`:
   - Find `COASTLINE_POINTS` array
   - Replace with local coastal coordinates from OpenStreetMap

7. **Install and start the service**:
   ```bash
   sudo cp flight-dashboard.service /etc/systemd/system/
   # Edit the service file to set correct paths and username
   sudo systemctl daemon-reload
   sudo systemctl enable flight-dashboard
   sudo systemctl start flight-dashboard
   ```

8. **Access the dashboard**: `http://<pi-ip>:8080`

### Optional: Kiosk display Pi

On a second Pi with a touchscreen, create `~/.config/autostart/adsb-dashboard.desktop`:
```ini
[Desktop Entry]
Type=Application
Name=ADS-B Dashboard
Exec=chromium --kiosk --start-fullscreen --no-first-run --password-store=basic http://BACKEND-PI-IP:8080/
X-GNOME-Autostart-enabled=true
```

## Service Management

```bash
sudo systemctl status flight-dashboard     # check if running
sudo systemctl restart flight-dashboard    # restart after code changes
sudo systemctl stop flight-dashboard       # stop
sudo journalctl -u flight-dashboard -f     # tail logs
sudo journalctl -u fr24feed -f             # tail FR24 feeder logs
```

## Deploying Code Changes

The Pi runs from a local directory (not a git clone). To deploy updates:
```bash
scp flight_dashboard/app.py user@pi-ip:~/flight_dashboard/app.py
scp flight_dashboard/templates/index.html user@pi-ip:~/flight_dashboard/templates/index.html
ssh user@pi-ip "sudo systemctl restart flight-dashboard"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/aircraft` | GET | All tracked aircraft with enriched data |
| `/api/settings/seen-threshold` | GET | Current seen threshold value |
| `/api/settings/seen-threshold` | POST | Set seen threshold `{"value": 30}` (10–300) |

## Aircraft Data Fields (from `/api/aircraft`)

Each aircraft object includes:
- `callsign`, `icao_hex`, `registration`, `airline`, `aircraft_type`
- `altitude_baro`, `altitude_gps`, `ground_speed`, `heading`
- `vertical_rate`, `vertical_status`, `vertical_icon`
- `lat`, `lon` — position (only present if aircraft broadcasts ADS-B position)
- `distance_mi` — distance from antenna in miles (only if lat/lon present)
- `bearing_deg`, `bearing_cardinal`, `bearing_cardinal16` — bearing from antenna
- `aircraft_class` — classification: `military`, `heavy`, `emergency`, or empty
- `squawk`, `rssi`, `seen`, `messages`
- `manufacturer`, `model`, `typecode`, `owner`, `built`, `age`, `category`

**Note:** Not all aircraft broadcast position. Mode S-only aircraft have altitude/speed but no lat/lon.

## Common Failure Modes

| Symptom | Check |
|---------|-------|
| "aircraft.json not found" | `ls -la /run/dump1090/` — does the file exist? |
| File exists but no aircraft | FR24 procargs missing `--write-json /run/dump1090` |
| Permission denied reading JSON | `sudo chown -R fr24:fr24 /run/dump1090/` |
| FR24 feeder won't start | `sudo journalctl -u fr24feed -n 50` — check for dongle conflicts |
| Dashboard shows no data | `curl http://localhost:8080/api/aircraft` — check Flask is running |
| Aircraft DB shows `---` | Run `venv/bin/python3 download_db.py` to generate `data/aircraft_db.json` |
| "Reconnecting..." flashing | Brief API drops — auto-recovers. Check `systemctl is-active flight-dashboard` |
| Radar coastline wrong | Update `COASTLINE_POINTS` in index.html for your location |

## Demo Mode

To test without hardware:
```bash
DEMO_MODE=true venv/bin/python3 flight_dashboard/app.py
```
Uses 6 hardcoded sample flights near Seattle.
