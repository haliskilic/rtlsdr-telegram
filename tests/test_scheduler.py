"""Zamanlayıcı seçim mantığı — sahte (fake) bileşenlerle."""
import time
import tempfile
from pathlib import Path

from rtlsdr_telegram.config import load_config
from rtlsdr_telegram.storage import Storage
from rtlsdr_telegram.scheduler import Scheduler
from rtlsdr_telegram.events import Category


class FakeSDR:
    def __init__(self):
        self.info = None
        self.gain = 40
    def device_present(self):
        return True
    def lease(self, owner):
        class _L:
            def __enter__(self2): return self
            def __exit__(self2, *a): return False
        return _L()


class FakeTarget:
    def __init__(self, key, cat=Category.TARAMA, cls="opportunistic", prio=5, period=100, device=True):
        self.KEY = key
        self.CATEGORY = cat
        self.CLASS = cls
        self.enabled = True
        self.priority = prio
        self.period_s = period
        self.dwell_s = 20
        self.last_run = 0
        self.event_count = 0
        self.band_label = key
        self._device = device
        self.ran = False
    def needs_device(self): return self._device
    def display_name(self): return self.KEY
    def wants_slot(self, now): return (now - (self.last_run + self.period_s)) >= 0
    def due_in(self, now): return max(0, (self.last_run + self.period_s) - now)
    def next_window(self, now): return None
    def run_slot(self, stop, dur): self.ran = True


def _sched(targets):
    cfg = load_config()
    d = tempfile.mkdtemp()
    st = Storage(Path(d) / "t.db")
    return Scheduler(cfg, FakeSDR(), targets, _Log(), _Disp(), st), st


class _Log:
    def __getattr__(self, n): return lambda *a, **k: None
    def getChild(self, n): return self


class _Disp:
    transcriber = None
    def submit(self, ev): pass


def test_emergency_wins():
    emerg = FakeTarget("emergency", Category.ACIL, prio=0, period=0)
    normal = FakeTarget("ism", Category.ISM, prio=5, period=0)
    sched, st = _sched([emerg, normal])
    action = sched._choose_action()
    assert action[0] == "target" and action[1].KEY == "emergency"


def test_mute_skips_category():
    emerg = FakeTarget("emergency", Category.ACIL, prio=0, period=0)
    sched, st = _sched([emerg])
    sched.mute("Acil Durum")
    action = sched._choose_action()
    # acil susturuldu → başka aday yok
    assert action is None or action[1].KEY != "emergency"


def test_boost_brings_forward():
    a = FakeTarget("adsb", Category.HAVACILIK, prio=5, period=99999)
    a.last_run = time.time()  # normalde sırada değil
    sched, st = _sched([a])
    assert sched._choose_action() is None
    sched.boost("adsb")
    action = sched._choose_action()
    assert action and action[1].KEY == "adsb"


def test_adhoc_priority():
    a = FakeTarget("ism", Category.ISM, period=0)
    sched, st = _sched([a])
    sched.add_adhoc(145.5, 30)
    action = sched._choose_action()
    assert action[0] == "adhoc"


def test_normal_cycle_picks_overdue():
    a = FakeTarget("ism", Category.ISM, prio=5, period=0)
    b = FakeTarget("aprs", Category.AMATOR, prio=5, period=0)
    a.last_run = time.time() - 500  # daha gecikmiş
    b.last_run = time.time() - 100
    sched, st = _sched([a, b])
    action = sched._choose_action()
    assert action[1].KEY == "ism"
