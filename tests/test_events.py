"""Olay modeli ve mesaj biçimlendirme testleri."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from rtlsdr_telegram.events import (Event, Category, fmt_freq, fmt_duration, fmt_time, esc)
from rtlsdr_telegram.i18n import set_language, EN, TR


TZ = ZoneInfo("Europe/Istanbul")


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def test_fmt_freq():
    assert fmt_freq(131.725) == "131.725 MHz"
    assert fmt_freq(1090.0) == "1090.000 MHz"
    assert fmt_freq(1541.45).endswith("MHz")
    assert fmt_freq(None) == "—"


def test_fmt_duration_en_and_tr():
    assert fmt_duration(5) == "5.0 s"
    assert fmt_duration(42) == "42 s"
    assert "min" in fmt_duration(125)
    assert "h" in fmt_duration(3700)
    assert fmt_duration(None) == "—"
    set_language("tr")
    assert fmt_duration(42) == "42 sn" and "dk" in fmt_duration(125) and "sa" in fmt_duration(3700)


def test_category_parse_bilingual():
    assert Category.parse("havacılık") == Category.HAVACILIK
    assert Category.parse("Aviation") == Category.HAVACILIK
    assert Category.parse("aviation") == Category.HAVACILIK
    assert Category.parse("DENIZ") == Category.DENIZCILIK
    assert Category.parse("Maritime") == Category.DENIZCILIK
    assert Category.parse("gsm") == Category.HUCRESEL
    assert Category.parse("unknown-xyz") is None
    assert Category.HAVACILIK.value == "aviation"  # database key is language neutral


def test_i18n_key_parity():
    assert set(EN) == set(TR), (set(EN) ^ set(TR))
    for k, v in EN.items():
        assert "{" not in v or "{" in TR[k], k   # placeholders present in both


def test_header_contains_all_fields_en():
    ev = Event("ADS-B Aircraft", Category.HAVACILIK, band="1090 MHz ADS-B", freq_mhz=1090.0,
               summary="New aircraft THY123", signal="-12 dBFS", lat=41.1, lon=29.1)
    html = ev.header_html(TZ, 41.0, 29.0)
    for label in ("Band", "Frequency", "Time", "Duration", "Signal", "Location", "Summary"):
        assert label in html
    assert "✈️" in html and "ADS-B Aircraft" in html and "Aviation" in html
    assert "km" in html and " N" in html or "NE" in html  # distance + English compass


def test_header_turkish():
    set_language("tr")
    ev = Event("ADS-B Uçak", Category.HAVACILIK, band="1090 MHz ADS-B", freq_mhz=1090.0,
               summary="Yeni uçak", lat=41.1, lon=29.1)
    html = ev.header_html(TZ, 41.0, 29.0)
    for label in ("Frekans aralığı", "Yakalanan frekans", "Zaman", "Süre", "Sinyal gücü", "Konum", "Özet"):
        assert label in html
    assert "Havacılık" in html


def test_html_escaping():
    ev = Event("Test", Category.TARAMA, summary="<script>&", body="a < b & c > d")
    html = ev.to_html(TZ, None, None)
    assert "<script>" not in html.replace("&lt;script&gt;", "")
    assert "&lt;" in html or "&amp;" in html


def test_transcript_in_body():
    ev = Event("Airband Voice", Category.HAVACILIK)
    ev.transcript = "Tower cleared for takeoff"
    ev.transcript_status = "done"
    ev.transcript_lang = "en"
    body = ev.body_html()
    assert "Transcript" in body and "cleared for takeoff" in body
    set_language("tr")
    assert "Transkripsiyon" in ev.body_html()


def test_transcript_failed_note():
    ev = Event("Voice", Category.DENIZCILIK)
    ev.transcript_status = "failed"
    assert "no text" in ev.body_html()
    set_language("tr")
    assert "çıkarılamadı" in ev.body_html()


def test_json_roundtrip_and_legacy_category():
    ev = Event("AIS Vessel", Category.DENIZCILIK, freq_mhz=161.975, lat=40.9, lon=29.0, summary="Test")
    ev2 = Event.from_json(ev.to_json())
    assert ev2.event_type == ev.event_type and ev2.category == Category.DENIZCILIK and ev2.freq_mhz == 161.975
    legacy = ev.to_dict(); legacy["category"] = "Denizcilik"   # written by early versions
    assert Event.from_dict(legacy).category == Category.DENIZCILIK


def test_time_has_utc_and_local():
    dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    txt = fmt_time(dt, TZ)
    assert "UTC" in txt
    assert "2026-01-15" in txt
