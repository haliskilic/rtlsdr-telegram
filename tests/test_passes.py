"""Satellite pass handling: one report per pass, a single retry after a failed start,
and the dongle goes back to the normal cycle in between (no 1 Hz spin in the window)."""
import logging
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rtlsdr_telegram.config import load_config
from rtlsdr_telegram.storage import Storage
from rtlsdr_telegram.satellites import Pass
from rtlsdr_telegram.targets import TargetContext
from rtlsdr_telegram.targets.meteor import MeteorTarget
from rtlsdr_telegram.targets.iss import ISSTarget


class _Disp:
    def __init__(self):
        self.sent = []

    def submit(self, ev):
        self.sent.append(ev)


class _SDR:
    ppm = 0
    device_index = 0
    bin_rtl_fm = "/usr/bin/rtl_fm"

    def wait_ready(self):
        pass

    def mark_released(self):
        pass


def _make(cls, key):
    cfg = load_config()
    st = Storage(Path(tempfile.mkdtemp()) / "t.db")
    disp = _Disp()
    ctx = TargetContext(cfg=cfg, sdr=_SDR(), storage=st, dispatcher=disp, transcriber=None,
                        logger=logging.getLogger("t"), audio=None)
    cls.register_defaults(cfg, key)
    tgt = cls(key, ctx)
    tgt._tools_ok = True
    return tgt, disp


def _pass(seconds_left: float, name="METEOR-M2 3"):
    now = datetime.now(timezone.utc)
    return Pass(name, now - timedelta(seconds=30), now, now + timedelta(seconds=seconds_left), 45.0)


def test_meteor_failed_start_retries_once_then_reports_once():
    tgt, disp = _make(MeteorTarget, "meteor")
    p = _pass(400)
    sat = {"name": "METEOR-M2 3", "freq_mhz": 137.9}
    tgt._pending = (p, sat)
    tgt._run_pass = lambda p, sat, stop, dur: (-6, [])  # SatDump aborts immediately
    stop = threading.Event()

    tgt.run_slot(stop, 400)
    # first failure: back-off, nothing sent, the pass is kept for the retry
    assert disp.sent == []
    assert tgt._pending is not None
    assert time.time() + 30 < tgt.pass_retry_after < time.time() + 120

    tgt.pass_retry_after = 0
    tgt.run_slot(stop, 300)
    # second failure: exactly one notice that names the tool failure, done until the window ends
    assert len(disp.sent) == 1
    assert "SatDump" in disp.sent[0].body and "-6" in disp.sent[0].body
    assert tgt._pending is None
    assert tgt.pass_retry_after >= p.set.timestamp()

    tgt.pass_retry_after = 0
    tgt._pending = (p, sat)  # even if the same pass comes back, nothing more is sent
    tgt.run_slot(stop, 200)
    assert len(disp.sent) == 1


def test_meteor_no_retry_when_window_nearly_over():
    tgt, disp = _make(MeteorTarget, "meteor")
    p = _pass(60)
    tgt._pending = (p, {"name": "METEOR-M2 4", "freq_mhz": 137.1})
    tgt._run_pass = lambda p, sat, stop, dur: (-6, [])
    tgt.run_slot(threading.Event(), 60)
    assert len(disp.sent) == 1 and tgt.pass_retry_after >= p.set.timestamp()


def test_meteor_success_sends_images_once():
    tgt, disp = _make(MeteorTarget, "meteor")
    p = _pass(300)
    tgt._pending = (p, {"name": "METEOR-M2 3", "freq_mhz": 137.9})
    tgt._run_pass = lambda p, sat, stop, dur: (0, ["/tmp/a.png", "/tmp/b.png"])
    tgt.run_slot(threading.Event(), 300)
    assert len(disp.sent) == 1
    ev = disp.sent[0]
    assert len(ev.attachments) == 2 and ev.attachments[0].kind == "photo"
    assert "2" in ev.summary
    assert tgt.pass_retry_after >= p.set.timestamp()


def test_iss_failed_start_retries_once_then_one_notice():
    tgt, disp = _make(ISSTarget, "iss")
    p = _pass(400, name="ISS")
    tgt._pending = p
    tgt._run_voice = lambda stop, dur, p, sstv=False: False  # recorder returned at once
    stop = threading.Event()
    tgt.run_slot(stop, 400)
    assert disp.sent == [] and tgt._pending is not None and tgt.pass_retry_after > time.time() + 30
    tgt.pass_retry_after = 0
    tgt.run_slot(stop, 300)
    assert len(disp.sent) == 1 and tgt._pending is None and tgt.pass_retry_after >= p.set.timestamp()
    tgt.pass_retry_after = 0
    tgt._pending = p
    tgt.run_slot(stop, 200)
    assert len(disp.sent) == 1
