"""Olay modeli ve mesaj biçimlendirme testleri."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from rtlsdr_telegram.events import (Event, Category, fmt_freq, fmt_duration, fmt_time, esc)


TZ = ZoneInfo("Europe/Istanbul")


def test_fmt_freq():
    assert fmt_freq(131.725) == "131.725 MHz"
    assert fmt_freq(1090.0) == "1090.000 MHz"
    assert fmt_freq(1541.45).endswith("MHz")
    assert fmt_freq(None) == "—"


def test_fmt_duration():
    assert fmt_duration(5) == "5.0 sn"
    assert fmt_duration(42) == "42 sn"
    assert "dk" in fmt_duration(125)
    assert "sa" in fmt_duration(3700)
    assert fmt_duration(None) == "—"


def test_category_parse():
    assert Category.parse("havacılık") == Category.HAVACILIK
    assert Category.parse("DENIZ") == Category.DENIZCILIK
    assert Category.parse("gsm") == Category.HUCRESEL
    assert Category.parse("bilinmeyen") is None


def test_header_contains_all_fields():
    ev = Event("ADS-B Uçak", Category.HAVACILIK, band="1090 MHz ADS-B", freq_mhz=1090.0,
               summary="Yeni uçak THY123", signal="-12 dBFS", lat=41.1, lon=29.1)
    html = ev.header_html(TZ, 41.0, 29.0)
    for label in ("Frekans aralığı", "Yakalanan frekans", "Zaman", "Süre",
                  "Sinyal gücü", "Konum", "Özet"):
        assert label in html
    assert "✈️" in html
    assert "ADS-B Uçak" in html
    assert "km" in html  # mesafe hesaplandı


def test_html_escaping():
    ev = Event("Test", Category.TARAMA, summary="<script>&", body="a < b & c > d")
    html = ev.to_html(TZ, None, None)
    assert "<script>" not in html.replace("&lt;script&gt;", "")
    assert "&lt;" in html or "&amp;" in html


def test_transcript_in_body():
    ev = Event("Hava Bandı Ses", Category.HAVACILIK)
    ev.transcript = "Tower cleared for takeoff"
    ev.transcript_status = "done"
    ev.transcript_lang = "en"
    body = ev.body_html()
    assert "Transkripsiyon" in body
    assert "cleared for takeoff" in body


def test_transcript_failed_note():
    ev = Event("Ses", Category.DENIZCILIK)
    ev.transcript_status = "failed"
    assert "çıkarılamadı" in ev.body_html()


def test_json_roundtrip():
    ev = Event("AIS Gemi", Category.DENIZCILIK, freq_mhz=161.975, lat=40.9, lon=29.0,
               summary="Test gemi")
    s = ev.to_json()
    ev2 = Event.from_json(s)
    assert ev2.event_type == ev.event_type
    assert ev2.category == Category.DENIZCILIK
    assert ev2.freq_mhz == 161.975


def test_time_has_utc_and_local():
    dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    txt = fmt_time(dt, TZ)
    assert "UTC" in txt
    assert "2026-01-15" in txt
