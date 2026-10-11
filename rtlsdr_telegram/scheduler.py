"""Tek dongle zamanlayıcı / tarama mantığı (madde 8).

Hedefler iki sınıfta yönetilir:
  (a) "waiting" — zamanlanmış pencere gerektirenler (uydu/ISS geçişleri). TLE'den
      hesaplanan pencerede o frekansa öncelik verilir.
  (b) "opportunistic" — fırsatçı taranlar (ses bantları, ISM, spektrum, ADS-B...).
      Kendi periyotlarına göre sırayla dongle alır.

Çakışmada öncelik sırası:
    Acil Durum  >  zamanlanmış uydu geçişi  >  kullanıcı /oncelik  >  normal döngü

Döngü durumu /durum ile görünür: şu an hangi frekans dinleniyor, sıradaki ne.
Dongle yoksa döngü bekler ve durumu bildirir; takılınca otomatik devam eder.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .events import Category


@dataclass
class AdhocRequest:
    freq_mhz: float
    mode: str
    seconds: float
    requested_by: int
    reply: dict | None = None
    created: float = field(default_factory=time.time)


@dataclass
class SchedState:
    current_target: str = ""
    current_name: str = ""
    current_freq_text: str = "—"
    current_since: float = 0.0
    next_target: str = ""
    next_info: str = ""
    device_present: bool = False
    last_device_note: float = 0.0


class Scheduler:
    def __init__(self, cfg, sdr, targets, logger, dispatcher, storage):
        self.cfg = cfg
        self.sdr = sdr
        self.targets = targets
        self.by_key = {t.KEY: t for t in targets}
        self.log = logger
        self.dispatcher = dispatcher
        self.st = storage
        sc = cfg.section("scheduler")
        self.min_slot_s = float(sc.get("min_slot_s", 10))
        self.pass_lead_s = float(sc.get("pass_lead_s", 30))
        self.boost_minutes = float(sc.get("boost_minutes", 30))
        self.no_device_retry_s = float(sc.get("no_device_retry_s", 60))
        self.grace_s = float(sc.get("grace_s", 8))
        self.adhoc_default_s = float(sc.get("adhoc_default_s", 120))
        self.state = SchedState()
        self.muted: set[str] = set(self.st.kv_get("muted_categories", []) or [])
        self.boosts: dict[str, float] = {}
        self.adhoc: list[AdhocRequest] = []
        self._adhoc_lock = threading.Lock()
        self._stop = threading.Event()
        self._slot_stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.run_id: int | None = None

    # ------------------------------------------------------------- yaşam
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._slot_stop.set()
        if self._thread:
            self._thread.join(timeout=15)

    # ------------------------------------------------- dışarıdan kontrol
    def mute(self, category: str) -> bool:
        cat = Category.parse(category)
        if not cat:
            return False
        self.muted.add(cat.value)
        self.st.kv_set("muted_categories", list(self.muted))
        return True

    def unmute(self, category: str) -> bool:
        cat = Category.parse(category)
        if not cat:
            return False
        self.muted.discard(cat.value)
        self.st.kv_set("muted_categories", list(self.muted))
        return True

    def is_muted(self, cat: Category) -> bool:
        return cat.value in self.muted

    def boost(self, key: str) -> bool:
        if key not in self.by_key:
            return False
        self.boosts[key] = time.time() + self.boost_minutes * 60
        t = self.by_key[key]
        t.last_run = 0  # hemen sıraya gelsin
        return True

    def add_adhoc(self, freq_mhz: float, seconds: float | None = None, mode: str = "fm",
                  requested_by: int = 0, reply: dict | None = None) -> AdhocRequest:
        req = AdhocRequest(freq_mhz, mode, seconds or self.adhoc_default_s, requested_by, reply)
        with self._adhoc_lock:
            self.adhoc.append(req)
        self._slot_stop.set()  # mevcut slotu bitirip ad-hoc'a geç
        return req

    def interrupt_slot(self):
        self._slot_stop.set()

    # ------------------------------------------------------------- durum
    def status_dict(self) -> dict:
        s = self.state
        return {
            "current_target": s.current_target, "current_name": s.current_name,
            "current_freq": s.current_freq_text,
            "current_since_s": (time.time() - s.current_since) if s.current_since else 0,
            "next_target": s.next_target, "next_info": s.next_info,
            "device_present": s.device_present,
            "muted": sorted(self.muted),
            "boosts": {k: max(0, int(v - time.time())) for k, v in self.boosts.items() if v > time.time()},
            "queue_len": self.st.queue_len(),
        }

    def active_targets(self) -> list:
        return [t for t in self.targets if t.enabled]

    # --------------------------------------------------------- ana döngü
    def _loop(self):
        while not self._stop.is_set():
            # 1) dongle var mı?
            if not self.sdr.device_present():
                self.state.device_present = False
                self._note_no_device()
                self._stop.wait(self.no_device_retry_s)
                continue
            if not self.state.device_present:
                self.state.device_present = True
                self.log.info("dongle hazır: %s", self.sdr.info.detail if self.sdr.info else "")
            # 2) sıradaki eylemi seç
            action = self._choose_action()
            if action is None:
                self.state.current_target = ""
                self.state.current_name = "boşta"
                self.state.current_freq_text = "—"
                self._stop.wait(2)
                continue
            self._run_action(action)

    def _note_no_device(self):
        now = time.time()
        if now - self.state.last_device_note > 300:
            self.state.last_device_note = now
            detail = self.sdr.info.detail if self.sdr.info else "dongle bulunamadı"
            self.log.warning("SDR dongle yok: %s", detail)

    # --------------------------------------------------- eylem seçimi
    def _choose_action(self):
        now = time.time()
        # a) ad-hoc istek (kullanıcı /tara) — hemen
        with self._adhoc_lock:
            if self.adhoc:
                return ("adhoc", self.adhoc.pop(0))
        # b) aktif/yaklaşan uydu geçişi (waiting hedefler)
        pass_action = self._pending_pass(now)
        # c) acil durum hedefi (en yüksek öncelik) — süresi geldiyse
        emerg = self.by_key.get("emergency")
        emerg_due = emerg and emerg.enabled and not self.is_muted(emerg.CATEGORY) and emerg.wants_slot(now) \
            and self.sdr  # device zaten kontrol edildi
        # Öncelik: Acil > uydu geçişi > boost > normal
        # Ancak aktif (şu an içinde) geçiş acil durumla yarışırsa: kısa acil kontrolünü araya sıkıştır.
        if emerg_due and not (pass_action and pass_action[2] == "active"):
            return ("target", emerg, "acil")
        if pass_action:
            return ("target", pass_action[1], "uydu")
        if emerg_due:
            return ("target", emerg, "acil")
        # d) kullanıcı boost
        for key, exp in list(self.boosts.items()):
            if exp <= now:
                self.boosts.pop(key, None)
                continue
            t = self.by_key.get(key)
            if t and t.enabled and not self.is_muted(t.CATEGORY) and t.wants_slot(now):
                return ("target", t, "boost")
        # e) normal döngü: süresi gelen fırsatçı hedefler arasından en 'gecikmişi'
        candidates = []
        for t in self.targets:
            if not t.enabled or self.is_muted(t.CATEGORY):
                continue
            if t.CLASS == "waiting":
                continue  # yalnız pencere içinde
            if not t.needs_device():
                continue  # cihaz gerektirmeyen (auto_rx) ayrı ele alınır
            overdue = now - (t.last_run + t.period_s)
            if overdue >= 0:
                candidates.append((t.priority, -overdue, t))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]))
            self._set_next(candidates)
            return ("target", candidates[0][2], "normal")
        # f) cihaz gerektirmeyen hedefler (radiosonde auto_rx) — boşta çalıştır
        for t in self.targets:
            if t.enabled and not self.is_muted(t.CATEGORY) and not t.needs_device() and t.wants_slot(now):
                return ("target", t, "fırsat")
        return None

    def _pending_pass(self, now: float):
        """En yakın uydu/ISS geçişini döndürür: (rise, target, 'active'|'soon') ya da None."""
        best = None
        for t in self.targets:
            if t.CLASS != "waiting" or not t.enabled or self.is_muted(t.CATEGORY):
                continue
            if not hasattr(t, "next_window"):
                continue
            win = t.next_window(now)
            if not win:
                continue
            rise, set_t = win
            if rise - self.pass_lead_s <= now <= set_t:
                return (rise, t, "active")
            if best is None or rise < best[0]:
                best = (rise, t, "soon")
                self.state.next_target = t.KEY
                self.state.next_info = f"{t.display_name()} geçişi {self._fmt_eta(rise - now)}"
        # yaklaşan ama henüz pencerede değil — bekleme eylemi döndürme (normal döngü dönsün)
        return None

    def _set_next(self, candidates):
        if len(candidates) > 1:
            nxt = candidates[1][2]
            self.state.next_target = nxt.KEY
            self.state.next_info = f"{nxt.display_name()} ({nxt.band_label})"

    @staticmethod
    def _fmt_eta(secs: float) -> str:
        secs = max(0, int(secs))
        if secs < 90:
            return f"{secs} sn sonra"
        m = secs // 60
        if m < 60:
            return f"{m} dk sonra"
        return f"{m // 60} sa {m % 60} dk sonra"

    # ------------------------------------------------------ eylem çalıştır
    def _run_action(self, action):
        kind = action[0]
        if kind == "adhoc":
            self._run_adhoc(action[1])
            return
        _, target, reason = action
        duration = self._duration_for(target, reason)
        self._slot_stop.clear()
        self.state.current_target = target.KEY
        self.state.current_name = target.display_name()
        self.state.current_freq_text = target.band_label
        self.state.current_since = time.time()
        target.last_run = time.time()
        run_id = self.st.run_start(target.KEY, reason)
        before = target.event_count
        try:
            with self.sdr.lease(target.KEY):
                target.run_slot(self._combined_stop(), duration)
        except Exception as e:
            self.log.exception("hedef '%s' çöktü: %s", target.KEY, e)
            try:
                self.st.log_error(target.KEY, f"slot hata: {e}")
            except Exception:
                pass
        finally:
            self.st.run_end(run_id, target.event_count - before, None)
            self.state.current_target = ""

    def _run_adhoc(self, req):
        self.state.current_target = "adhoc"
        self.state.current_name = f"/tara {req.freq_mhz:.3f} MHz"
        self.state.current_freq_text = f"{req.freq_mhz:.4f} MHz ({req.mode.upper()})"
        self.state.current_since = time.time()
        self._slot_stop.clear()
        from .events import Event, Category, Attachment
        from .channel_maps import describe
        try:
            with self.sdr.lease("adhoc"):
                recorder = self._recorder
                freq_hz = int(req.freq_mhz * 1e6)
                segs = recorder.record_window(freq_hz, req.seconds, self._combined_stop(),
                                              mode=req.mode, audio_rate=16000, threshold_dbfs=-46.0,
                                              hangover_s=1.5, min_segment_s=0.5, max_segment_s=req.seconds,
                                              gain=self.sdr.gain, channel=None, prefix="adhoc")
        except Exception as e:
            self.log.warning("ad-hoc tarama hatası: %s", e)
            segs = []
        finally:
            self.state.current_target = ""
        band = describe(req.freq_mhz)
        if not segs:
            ev = Event("Geçici Tarama", Category.TARAMA, band=band, freq_mhz=req.freq_mhz,
                       summary=f"{band} — {req.seconds:.0f} sn dinlendi, etkinlik yok", priority=5)
            ev.reply_to = req.reply
            self.dispatcher.submit(ev)
            return
        for seg in segs:
            ev = Event("Geçici Tarama", Category.TARAMA, band=band, freq_mhz=req.freq_mhz,
                       summary=f"{band} — {seg.duration_s:.0f} sn yayın",
                       signal=f"{seg.peak_dbfs:.1f} dBFS (tepe)", signal_value=seg.peak_dbfs,
                       duration_s=seg.duration_s, priority=4,
                       attachments=[Attachment("voice", seg.final_path, caption=band)])
            ev.transcript_status = "pending"
            ev.reply_to = req.reply
            self.dispatcher.submit(ev)

    def _duration_for(self, target, reason) -> float:
        if reason == "uydu":
            win = target.next_window(time.time())
            if win:
                rise, sett = win
                return max(self.min_slot_s, min(sett - time.time(), sett - rise) + 5)
        return max(self.min_slot_s, target.dwell_s)

    def _combined_stop(self) -> threading.Event:
        # slot-stop ya da global-stop tetiklenince uyanan birleşik olay
        ev = threading.Event()

        def watch():
            while not ev.is_set():
                if self._stop.is_set() or self._slot_stop.is_set():
                    ev.set()
                    return
                time.sleep(0.2)
        threading.Thread(target=watch, daemon=True).start()
        return ev

    # recorder main tarafından atanır (ad-hoc için)
    _recorder = None
