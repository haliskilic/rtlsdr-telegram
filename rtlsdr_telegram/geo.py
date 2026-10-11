"""Geographic helpers: distance, bearing, location formatting."""
from __future__ import annotations

import math

from .i18n import compass_labels


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates (km)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 to point 2 (0–360, clockwise from north)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def compass(deg: float) -> str:
    """8-point compass abbreviation in the active language."""
    labels = compass_labels()
    return labels[int((deg + 22.5) // 45) % 8]


# Backwards-compatible alias used by older call sites.
compass_tr = compass


def format_location(lat: float | None, lon: float | None, station_lat: float | None = None,
                    station_lon: float | None = None) -> str:
    """Text for the header 'Location' field."""
    if lat is None or lon is None:
        return "—"
    txt = f"{lat:.4f}, {lon:.4f}"
    if station_lat is not None and station_lon is not None:
        d = haversine_km(station_lat, station_lon, lat, lon)
        b = bearing_deg(station_lat, station_lon, lat, lon)
        txt += f" ({d:.1f} km {compass(b)})"
    return txt


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=12/{lat:.5f}/{lon:.5f}"
