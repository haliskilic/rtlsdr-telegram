from rtlsdr_telegram.geo import haversine_km, bearing_deg, compass_tr, format_location


def test_haversine_known():
    # İstanbul - Ankara ~ 350 km
    d = haversine_km(41.0082, 28.9784, 39.9334, 32.8597)
    assert 340 < d < 360


def test_bearing_and_compass():
    # kuzeye
    assert compass_tr(bearing_deg(40, 29, 41, 29)) == "K"
    # doğuya
    assert compass_tr(bearing_deg(40, 29, 40, 30)) == "D"


def test_format_location():
    assert format_location(None, None) == "—"
    txt = format_location(41.0, 29.0, 40.0, 29.0)
    assert "km" in txt and "K" in txt
