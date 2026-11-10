"""Small geometry helpers shared by the dashboard modules."""

import math

EARTH_RADIUS_MI = 3958.8
FEET_PER_MILE = 5280.0


def distance_mi(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return EARTH_RADIUS_MI * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, 0 to 360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def elevation_deg(distance_miles, altitude_ft):
    """Angle above the horizon to an aircraft, seen from the antenna."""
    if distance_miles is None or altitude_ft is None:
        return None
    return math.degrees(math.atan2(max(altitude_ft, 0), max(distance_miles, 0.01) * FEET_PER_MILE))


def cross_track_mi(lat, lon, lat1, lon1, lat2, lon2):
    """Distance in miles from a point to the great-circle path between two points."""
    d13 = distance_mi(lat1, lon1, lat, lon) / EARTH_RADIUS_MI
    t13 = math.radians(bearing_deg(lat1, lon1, lat, lon))
    t12 = math.radians(bearing_deg(lat1, lon1, lat2, lon2))
    return abs(math.asin(math.sin(d13) * math.sin(t13 - t12))) * EARTH_RADIUS_MI
