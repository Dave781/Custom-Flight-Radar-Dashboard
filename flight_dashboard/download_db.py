#!/usr/bin/env python3
"""
Download aircraft database from OpenSky Network
Maps ICAO 24-bit hex codes to aircraft details
"""

import urllib.request
import csv
import json
import os

DB_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
DB_FILE = os.path.join(os.path.dirname(__file__), "data", "aircraft_db.json")

def download_and_convert():
    """Download CSV and convert to JSON lookup dict"""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

    print("Downloading aircraft database from OpenSky Network...")
    print("This may take a minute...")

    # Download CSV
    csv_path = "/tmp/aircraft_db.csv"
    urllib.request.urlretrieve(DB_URL, csv_path)
    print(f"Downloaded to {csv_path}")

    # Convert to JSON dict keyed by ICAO hex
    print("Converting to JSON format...")
    aircraft_db = {}

    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            icao = row.get('icao24', '').strip().lower()
            if icao:
                aircraft_db[icao] = {
                    'registration': row.get('registration', '').strip(),
                    'manufacturer': row.get('manufacturername', '').strip(),
                    'model': row.get('model', '').strip(),
                    'typecode': row.get('typecode', '').strip(),
                    'operator': row.get('operatoricao', '').strip(),
                    'owner': row.get('owner', '').strip(),
                    'built': row.get('built', '').strip(),
                    'category': row.get('categoryDescription', '').strip(),
                }

    # Save as JSON
    with open(DB_FILE, 'w') as f:
        json.dump(aircraft_db, f)

    print(f"Saved {len(aircraft_db)} aircraft to {DB_FILE}")

    # Cleanup
    os.remove(csv_path)
    print("Done!")

if __name__ == '__main__':
    download_and_convert()
