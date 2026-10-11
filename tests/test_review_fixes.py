"""İnceleme sonrası eklenen davranışlar için testler."""
import logging
import tempfile
from pathlib import Path

from rtlsdr_telegram.events import Event, Category, PRIO_EMERGENCY
from rtlsdr_telegram.targets.base import SlotCollector, audio_attachment
from rtlsdr_telegram.telegram import TelegramClient
from rtlsdr_telegram.satellites import SatellitePredictor
from rtlsdr_telegram.config import load_config
from rtlsdr_telegram.storage import Storage


class _Disp:
    def __init__(self): self.sent = []
    def submit(self, ev): self.sent.append(ev)


class _Target:
    """SlotCollector için asgari hedef taklidi."""
    KEY = "t"; CATEGORY = Category.ISM; priority = 5; band_label = "b"
    def __init__(self): self.d = _Disp()
    def make_event(self, event_type, **kw):
        kw.setdefault("band", self.band_label)
        kw.pop("freq_mhz", None); kw.pop("priority", None)
        return Event(event_type, self.CATEGORY, **kw)
    def emit(self, ev): self.d.submit(ev)


def test_slot_collector_individual_then_summary():
    t = _Target()
    c = SlotCollector(t, "Özet", individual_max=2, list_max=5)
    for i in range(2):
        c.add(f"öge {i}", Event(f"E{i}", Category.ISM))
    assert c.flush() == 2 and len(t.d.sent) == 2  # az öge → ayrı mesajlar
    t = _Target()
    c = SlotCollector(t, "Özet", individual_max=2, list_max=3)
    for i in range(7):
        c.add(f"öge {i}", Event(f"E{i}", Category.ISM), sort_key=i)
    assert c.flush() == 1 and len(t.d.sent) == 1  # çok öge → tek özet
    body = t.d.sent[0].body
    assert "öge 6" in body and "4 more" in body  # highest sort first, remaining count


def test_audio_attachment_kinds():
    assert audio_attachment("/x/a.ogg").kind == "voice"
    assert audio_attachment("/x/a.mp3").kind == "audio"
    assert audio_attachment("/x/a.wav").kind == "document"


def test_token_sanitized_and_tags_stripped():
    c = TelegramClient("123456:ABCDEF-secret", logging.getLogger("t"))
    assert "secret" not in c._san("hata https://api.telegram.org/bot123456:ABCDEF-secret/sendMessage")
    assert c._strip_tags("<b>x</b> &amp; <code>y</code>") == "x &amp; y"
    c.close()


def test_tle_parse_json_and_text():
    js = '{"line1":"1 25544U 98067A   26283.78925095  .00010839  00000+0  20582-3 0  9996","line2":"2 25544  51.6400 100.0 0001 90.0 270.0 15.50000000000000"}'
    tle = SatellitePredictor._parse_tle_response(js)
    assert tle and tle[0].startswith("1 25544")
    txt = "ISS\n1 25544U 98067A   26283.78925095  .00010839  00000+0  20582-3 0  9996\n2 25544  51.6400 100.0 0001 90.0 270.0 15.50000000000000\n"
    tle2 = SatellitePredictor._parse_tle_response(txt)
    assert tle2 and tle2[1].startswith("2 25544")
    assert SatellitePredictor._parse_tle_response("garbage") is None


def test_dispatcher_mute_bypass_for_emergency():
    from rtlsdr_telegram.dispatcher import Dispatcher
    cfg = load_config()
    st = Storage(Path(tempfile.mkdtemp()) / "t.db")

    class _Client:
        def send_message(self, *a, **k): return [1]
    class _Sched:
        def is_muted(self, cat): return cat == Category.DENIZCILIK
    d = Dispatcher(cfg, st, _Client(), logging.getLogger("d"))
    d.scheduler = _Sched()
    assert d._muted(Event("x", Category.DENIZCILIK, priority=5)) is True
    assert d._muted(Event("x", Category.DENIZCILIK, priority=PRIO_EMERGENCY)) is False
    assert d._muted(Event("x", Category.HAVACILIK, priority=5)) is False
    st.close()
