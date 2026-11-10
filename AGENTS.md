# AGENTS.md: guide for AI agents

How this project is laid out, how to run it, and what to check before changing it.

## What it does

A Raspberry Pi with an RTL-SDR dongle hears ADS-B messages from aircraft. The FlightRadar24 feeder (dump1090) decodes them into `aircraft.json`. This app reads that file and serves a live map on port 8080. A second Pi usually shows the map on a touchscreen in Chromium kiosk mode.

```
RTL-SDR dongle
    → fr24feed (runs dump1090)
        → /run/dump1090/aircraft.json      rewritten every second
            → flight_dashboard/app.py      Flask: enrich, track, serve
                → http://<pi-ip>:8080      map page, polls every second
                    → kiosk Pi             Chromium fullscreen
```

## Files

| File | Job |
|---|---|
| `flight_dashboard/app.py` | Flask app. Reads `aircraft.json`, adds database fields, distance, bearing, look angle, and icon type. Serves the API, the pages, and the map file |
| `flight_dashboard/tracker.py` | Background thread. Keeps trails, receiver health, and today's records |
| `flight_dashboard/lookups.py` | Route (adsbdb.com) and photo (planespotters.net) lookups with a disk cache. Hides routes that don't fit the plane's position |
| `flight_dashboard/geo.py` | Distance, bearing, elevation angle, cross-track distance |
| `flight_dashboard/demo.py` | Sample traffic for `DEMO_MODE=true` |
| `flight_dashboard/download_map.py` | Cuts the area around the antenna out of the Protomaps planet file into `data/map.pmtiles`, and builds `data/airports.json` from OurAirports. Standard library only |
| `flight_dashboard/download_db.py` | Builds `data/aircraft_db.json` from the OpenSky aircraft database |
| `flight_dashboard/templates/index.html` | Map page markup |
| `flight_dashboard/templates/debug.html` | Details page markup (`/debug`) |
| `flight_dashboard/static/js/app.js` | Map page logic: polling, selection, card, alerts, dimming |
| `flight_dashboard/static/js/style.js` | Map colors and layers |
| `flight_dashboard/static/js/icons.js` | Plane silhouettes and the altitude color scale |
| `flight_dashboard/static/js/debug.js` | Details page logic |
| `flight_dashboard/static/css/` | `app.css` for the map page, `debug.css` for the details page |
| `flight_dashboard/static/vendor/`, `static/fonts/` | MapLibre GL JS, PMTiles, and fonts, copied in so the kiosk needs no CDN. Versions and licenses are in `static/vendor/README.md` |
| `flight_dashboard/tests/test_dashboard.py` | Unit and API tests |
| `flight_dashboard/data/` | Generated files. Gitignored |

Not in the repo, on the Pi: `/etc/fr24feed.ini`, `/etc/systemd/system/flight-dashboard.service`, and `flight_dashboard/.env`.

## Run and test

```bash
cd flight_dashboard
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python3 download_map.py --lat 47.6062 --lon -122.3321   # once
DEMO_MODE=true venv/bin/python3 app.py                            # http://127.0.0.1:8080
venv/bin/python -m unittest discover -s tests
```

`DEMO_SCENARIO=emergency`, `stalled`, or `empty` shows those states. With `stalled`, also set `STALL_SECONDS=5` so the alert appears quickly.

The map needs WebGL and `requestAnimationFrame`. A hidden or background browser tab draws nothing, so take screenshots from a visible window or from headless Chrome.

## Settings

All are environment variables, also read from `flight_dashboard/.env`.

| Variable | Default | What it does |
|---|---|---|
| `HOME_LAT`, `HOME_LON` | none | Antenna location. Required outside demo mode. Never commit real values |
| `DASHBOARD_TITLE` | `Dave's ADS-B Radar` | Browser tab title |
| `PORT`, `HOST` | `8080`, `0.0.0.0` | Where the server listens |
| `MAP_RANGE_MI` | `25` | Miles from the antenna to the screen edge in the home view |
| `RANGE_RINGS_MI` | `5,10,20` | Range rings |
| `TRAIL_SECONDS` | `300` | Trail length |
| `SEEN_THRESHOLD` | `120` | Seconds of silence before a plane leaves the map. Also set from `/debug` |
| `STALL_SECONDS` | `180` | Seconds with no new messages before the "No signal" alert |
| `LOOKUPS` | `true` | Route and photo lookups |
| `CONTACT_URL` | this repo | Sent in the User-Agent of lookups. Planespotters requires a contact |
| `MAP_RADIUS_MI`, `MAP_MAX_ZOOM` | `80`, `12` | Used by `download_map.py` |
| `DEMO_MODE`, `DEMO_SCENARIO` | `false`, empty | Sample traffic |

## Setting up a new location

1. Put `HOME_LAT` and `HOME_LON` in `.env`.
2. Run `venv/bin/python3 download_map.py`. It downloads about 25 MB for the default 80-mile radius.
3. Restart the service.

There is no hand-drawn coastline any more. The map and airports come from the download.

## API

| Endpoint | Returns |
|---|---|
| `GET /` | Map page |
| `GET /debug` | Details page |
| `GET /api/aircraft` | Aircraft with positions, plus `receiver` and `today` |
| `GET /api/trails` | `{hex: [[lon, lat, altitude, time], ...]}` for the last `TRAIL_SECONDS` |
| `GET /api/flight/<hex>?callsign=&lat=&lon=&alt=` | `{route, photo}` for one aircraft. Either can be null |
| `GET /api/airports` | Airports and runways near the antenna |
| `GET /api/status` | Setup status for the details page |
| `GET /map.pmtiles` | The basemap. Read with HTTP range requests |
| `GET`, `POST /api/settings/seen-threshold` | Read or set the max contact age, `{"value": 30}`, 10 to 300 |

Fields on each aircraft in `/api/aircraft`:

- Identity: `callsign`, `icao_hex`, `registration`, `airline`, `aircraft_type`, `typecode`, `owner`, `built`, `age`
- Motion: `lat`, `lon`, `altitude_baro`, `altitude_gps`, `ground_speed`, `heading`, `vertical_rate`, `vertical_status`
- From the antenna: `distance_mi`, `bearing_deg`, `bearing_cardinal`, `bearing_cardinal16`, `elevation_deg`
- Class: `aircraft_class` (`military`, `heavy`, `normal`) and `icon` (`military`, `helicopter`, `heavy`, `prop`, `jet`)
- Radio: `squawk`, `rssi`, `seen`, `messages`

`receiver.state` is `ok`, `stalled` (decoder runs, no new messages for `STALL_SECONDS`), or `down` (no fresh `aircraft.json` for 30 seconds).

Aircraft without a position are left out. Mode S-only aircraft send altitude and speed but no latitude or longitude.

## How the page decides things

| Behavior | Rule | Where |
|---|---|---|
| Which plane the card shows | The plane highest above the horizon within `MAP_RANGE_MI`. Another plane must be 8° higher to take over. An emergency squawk always wins | `choose()` in `app.js` |
| Pinning | A tapped plane stays selected for 60 seconds without a touch | `tick()` in `app.js` |
| View reset | A moved map returns to the home view after 45 seconds without a touch | `tick()` in `app.js` |
| Plane position | The last report moved forward by its age, up to 8 seconds | `drawnPosition()` in `app.js` |
| Icon shape | Military hex block, then helicopter, heavy, and prop type codes, then the ADS-B emitter category | `pick_icon()` in `app.py` |
| Route shown or hidden | Below 12,000 ft the plane must be within 75 miles of one end. In cruise it must be near the direct path | `route_is_plausible()` in `lookups.py` |
| Night dimming | Dims when the sun is more than 4° below the horizon. The moon button cycles auto, on, off. Never dims in the first 90 seconds after load, so a kiosk launcher's render check sees a bright page | `applyDim()` in `app.js` |

## Deploying to the Pi

The Pi runs from a copied folder, not a git clone. Copy the code and leave the Pi's `data/`, `venv/`, and `.env` alone:

```bash
rsync -av --exclude data --exclude venv --exclude .env --exclude __pycache__ \
    flight_dashboard/ user@pi-ip:~/flight_dashboard/
ssh user@pi-ip "cd ~/flight_dashboard && venv/bin/python3 download_map.py"   # first time only
ssh user@pi-ip "sudo systemctl restart flight-dashboard"
```

The page URLs carry a version taken from file edit times, so the kiosk picks up new JavaScript and CSS on its next reload.

## Service commands

```bash
sudo systemctl status flight-dashboard
sudo systemctl restart flight-dashboard
sudo journalctl -u flight-dashboard -f
sudo journalctl -u fr24feed -f
```

## When something is wrong

| Symptom | Check |
|---|---|
| "No signal" on the map | Decoder is up but hears nothing. The RTL-SDR can wedge: it stays connected and sends no samples. Re-plug it or reset its USB port, then restart `fr24feed` |
| "Decoder offline" | `ls -la /run/dump1090/`. Is `aircraft.json` there and fresh? `procargs` in `/etc/fr24feed.ini` must include `--write-json /run/dump1090` |
| Permission denied reading JSON | `sudo chown -R fr24:fr24 /run/dump1090/` |
| "No map yet" | `venv/bin/python3 download_map.py`, then restart |
| No aircraft types | `venv/bin/python3 download_db.py` |
| "This browser cannot draw the map" | WebGL is off in the browser. Check `chrome://gpu` |
| Feeder won't start | `sudo journalctl -u fr24feed -n 50`. Look for another process holding the dongle |
