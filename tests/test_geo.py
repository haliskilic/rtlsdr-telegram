from rtlsdr_telegram.geo import haversine_km, bearing_deg, compass, format_location
from rtlsdr_telegram.i18n import set_language


def test_haversine_known():
    # İstanbul - Ankara ~ 350 km
    d = haversine_km(41.0082, 28.9784, 39.9334, 32.8597)
    assert 340 < d < 360


def test_bearing_and_compass():
    set_language("en")
    assert compass(bearing_deg(40, 29, 41, 29)) == "N"
    assert compass(bearing_deg(40, 29, 40, 30)) == "E"
    set_language("tr")
    assert compass(bearing_deg(40, 29, 41, 29)) == "K"
    assert compass(bearing_deg(40, 29, 40, 30)) == "D"
    set_language("en")


def test_format_location():
    set_language("en")
    assert format_location(None, None) == "—"
    txt = format_location(41.0, 29.0, 40.0, 29.0)
    assert "km" in txt and "N" in txt
