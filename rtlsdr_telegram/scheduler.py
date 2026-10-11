"""Single-dongle scheduler / scan logic (spec section 8).

Targets fall into three classes:
  "pass"          — satellite/ISS passes computed from TLE; they get the dongle
                    during the pass window.
  "waiting"       — targets that need dwell time on their frequency (ADS-B, AIS,
                    ACARS, radiosondes); part of the normal cycle with long dwell.
  "opportunistic" — voice bands, ISM, APRS, spectrum ...

Conflict priority:
    Emergency  >  scheduled satellite pass  >  user /priority  >  normal cycle

The normal cycle is fair: score = (lateness / period) / priority, so lower
priority targets still get their turn once they are proportionally later, and
a target that never ran is always served first. The state is visible with
/status (what is being listened to now, what comes next). Without a dongle the
loop waits and reports; it resumes automatically when the dongle appears.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .events import Category
from .i18n import t as _t


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
    next_pass_info: str = ""
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

    # ------------------------------------------------------------- lifecycle
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._slot_stop.set()
        if self._thread:
            self._thread.join(timeout=15)

    # ------------------------------------------------- external control
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
        t.last_run = 0  # becomes due immediately
        return True

    def add_adhoc(self, freq_mhz: float, seconds: float | None = None, mode: str = "fm",
                  requested_by: int = 0, reply: dict | None = None) -> AdhocRequest:
        req = AdhocRequest(freq_mhz, mode, seconds or self.adhoc_default_s, requested_by, reply)
        with self._adhoc_lock:
            self.adhoc.append(req)
        self._slot_stop.set()  # end the current slot and switch to the ad-hoc request
        return req

    def interrupt_slot(self):
        self._slot_stop.set()

    # ------------------------------------------------------------- status
    def status_dict(self) -> dict:
        s = self.state
        return {
            "current_target": s.current_target, "current_name": s.current_name,
            "current_freq": s.current_freq_text,
            "current_since_s": (time.time() - s.current_since) if s.current_since else 0,
            "next_target": s.next_target, "next_info": s.next_info,
            "next_pass_info": s.next_pass_info,
            "device_present": s.device_present,
            "muted": sorted(self.muted),
            "boosts": {k: max(0, int(v - time.time())) for k, v in self.boosts.items() if v > time.time()},
            "queue_len": self.st.queue_len(),
        }

    def active_targets(self) -> list:
        return [t for t in self.targets if t.enabled]

    # --------------------------------------------------------- main loop
    def _loop(self):
        while not self._stop.is_set():
            # 1) is the dongle present?
            if not self.sdr.device_present():
                self.state.device_present = False
                self._note_no_device()
                self._stop.wait(self.no_device_retry_s)
                continue
            if not self.state.device_present:
                self.state.device_present = True
                self.log.info("dongle ready: %s", self.sdr.info.detail if self.sdr.info else "")
            # 2) choose the next action
            action = self._choose_action()
            if action is None:
                self.state.current_target = ""
                self.state.current_name = _t("status.idle")
                self.state.current_freq_text = "—"
                self._stop.wait(2)
                continue
            self._run_action(action)

    def _note_no_device(self):
        now = time.time()
        if now - self.state.last_device_note > 300:
            self.state.last_device_note = now
            detail = self.sdr.info.detail if self.sdr.info else "dongle not found"
            self.log.warning("SDR dongle missing: %s", detail)

    # --------------------------------------------------- action selection
    def _choose_action(self):
        now = time.time()
        # a) ad-hoc request (user /scan) — immediately
        with self._adhoc_lock:
            if self.adhoc:
                return ("adhoc", self.adhoc.pop(0))
        # b) active/imminent satellite pass
        pass_action = self._pending_pass(now)
        # c) emergency target (highest priority) when due
        emerg = self.by_key.get("emergency")
        emerg_due = bool(emerg and emerg.enabled and not self.is_muted(emerg.CATEGORY)
                         and emerg.check_tools() and emerg.wants_slot(now))
        # Priority: emergency > satellite pass > boost > normal
        # (an active pass is not interrupted for the short emergency check)
        if emerg_due and not (pass_action and pass_action[2] == "active"):
            return ("target", emerg, "acil")
        if pass_action:
            return ("target", pass_action[1], "uydu")
        if emerg_due:
            return ("target", emerg, "acil")
        # d) user boost
        for key, exp in list(self.boosts.items()):
            if exp <= now:
                self.boosts.pop(key, None)
                continue
            t = self.by_key.get(key)
            if t and t.enabled and not self.is_muted(t.CATEGORY) and t.wants_slot(now):
                return ("target", t, "boost")
        # e) normal cycle: the proportionally latest due target
        candidates = []
        for t in self.targets:
            if not t.enabled or self.is_muted(t.CATEGORY):
                continue
            if t.CLASS == "pass":
                continue  # satellite/ISS: only inside the TLE window (_pending_pass)
            if not t.needs_device():
                continue  # targets without a device (auto_rx) are handled separately
            if not t.check_tools():
                continue  # a target without its tool must not occupy the cycle
            overdue = now - (t.last_run + t.period_s)
            if overdue < 0:
                continue
            # Fair scheduling (aging): not every period fits on one dongle. If priority
            # were a strict class, priority 3–4 targets would always be "due" and
            # priority 5–6 targets (ISM/APRS/spectrum/GSM) would starve.
            # score = (lateness / period) / priority -> a lower-priority target wins once
            # it is proportionally later. A target that never ran always goes first
            # (first-sweep guarantee regardless of priority; ties: priority, config order).
            if t.last_run <= 0:
                score = float("inf")
            else:
                score = (overdue / max(1.0, t.period_s)) / max(1, int(t.priority))
            candidates.append((score, t))
        if candidates:
            candidates.sort(key=lambda x: (0 if x[0] == float("inf") else 1, -x[0] if x[0] != float("inf") else 0,
                                           x[1].priority))
            self._set_next(candidates)
            return ("target", candidates[0][1], "normal")
        # f) targets without a device (radiosonde auto_rx) — run when idle
        for t in self.targets:
            if t.enabled and not self.is_muted(t.CATEGORY) and not t.needs_device() and t.wants_slot(now):
                return ("target", t, "idle")
        return None

    def _pending_pass(self, now: float):
        """Return the nearest satellite/ISS pass as (rise, target, 'active'|'soon') or None."""
        best = None
        for t in self.targets:
            if t.CLASS != "pass" or not t.enabled or self.is_muted(t.CATEGORY):
                continue
            if not t.check_tools():
                continue
            if getattr(t, "pass_retry_after", 0.0) > now:
                continue  # attempted/finished for now: do not hold the dongle idle inside the window
            win = t.next_window(now)
            if not win:
                continue
            rise, set_t = win
            if rise - self.pass_lead_s <= now <= set_t:
                return (rise, t, "active")
            if best is None or rise < best[0]:
                best = (rise, t, "soon")
        if best:
            self.state.next_pass_info = _t("status.pass_eta", name=best[1].display_name(), eta=self._fmt_eta(best[0] - now))
        else:
            self.state.next_pass_info = ""
        return None

    def _set_next(self, candidates):
        if len(candidates) > 1:
            nxt = candidates[1][1]
            self.state.next_target = nxt.KEY
            self.state.next_info = f"{nxt.display_name()} ({nxt.band_label})"

    @staticmethod
    def _fmt_eta(secs: float) -> str:
        secs = max(0, int(secs))
        if secs < 90:
            return _t("eta.sec", n=secs)
        m = secs // 60
        if m < 60:
            return _t("eta.min", n=m)
        return _t("eta.h", h=m // 60, m=m % 60)

    # ------------------------------------------------------ run action
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
                self.sdr.note_device_ok()
                target.run_slot(self._slot_stop, duration)
        except Exception as e:
            self.log.exception("target '%s' crashed: %s", target.KEY, e)
            try:
                self.st.log_error(target.KEY, f"slot error: {e}")
            except Exception:
                pass
        finally:
            self.st.run_end(run_id, target.event_count - before, None)
            self.state.current_target = ""

    def _run_adhoc(self, req):
        self.state.current_target = "adhoc"
        self.state.current_name = f"/scan {req.freq_mhz:.3f} MHz"
        self.state.current_freq_text = f"{req.freq_mhz:.4f} MHz ({req.mode.upper()})"
        self.state.current_since = time.time()
        self._slot_stop.clear()
        from .events import Event, Category
        from .channel_maps import describe
        from .targets.base import audio_attachment
        try:
            with self.sdr.lease("adhoc"):
                recorder = self._recorder
                freq_hz = int(req.freq_mhz * 1e6)
                segs = recorder.record_window(freq_hz, req.seconds, self._slot_stop,
                                              mode=req.mode, audio_rate=16000, threshold_dbfs=-46.0,
                                              hangover_s=1.5, min_segment_s=0.5, max_segment_s=req.seconds,
                                              gain=self.sdr.gain, channel=None, prefix="adhoc",
                                              require_dynamics=False)
        except Exception as e:
            self.log.warning("ad-hoc scan error: %s", e)
            segs = []
        finally:
            self.state.current_target = ""
        band = describe(req.freq_mhz)
        if not segs:
            ev = Event(_t("evt.adhoc"), Category.TARAMA, band=band, freq_mhz=req.freq_mhz,
                       summary=_t("adhoc.none", band=band, s=f"{req.seconds:.0f}"), priority=5)
            ev.reply_to = req.reply
            self.dispatcher.submit(ev)
            return
        for seg in segs:
            ev = Event(_t("evt.adhoc"), Category.TARAMA, band=band, freq_mhz=req.freq_mhz,
                       summary=_t("adhoc.summary", band=band, s=f"{seg.duration_s:.0f}"),
                       signal=_t("common.peak_dbfs", v=f"{seg.peak_dbfs:.1f}"), signal_value=seg.peak_dbfs,
                       duration_s=seg.duration_s, priority=4,
                       attachments=[audio_attachment(seg.final_path, caption=band)])
            ev.transcript_status = "pending"
            ev.reply_to = req.reply
            self._submit(ev)

    def _duration_for(self, target, reason) -> float:
        if reason == "uydu":
            win = target.next_window(time.time())
            if win:
                rise, sett = win
                return max(self.min_slot_s, min(sett - time.time(), sett - rise) + 5)
        return max(self.min_slot_s, target.dwell_s)

    # assigned by the application: ad-hoc recorder and transcription routing
    _recorder = None
    tworker = None

    def _submit(self, ev):
        """Route audio events to the transcription worker, everything else to the queue."""
        if self.tworker is not None and ev.needs_transcription:
            self.tworker.submit(ev)
        else:
            self.dispatcher.submit(ev)

    # ------------------------------------------------------ pass list
    def upcoming_passes(self, hours: float = 24, limit: int = 8) -> list:
        """Upcoming passes of the enabled 'pass' targets (for /passes)."""
        sats = []
        pred = None
        for t in self.targets:
            if t.CLASS != "pass" or not t.enabled:
                continue
            pred = pred or getattr(t, "predictor", None)
            if t.KEY == "iss":
                sats.append({"norad": t.conf.get("norad", 25544), "name": "ISS",
                             "min_elevation": t.conf.get("min_elevation", 10)})
            else:
                for sd in t.conf.get("satellites", []):
                    sats.append({"norad": sd["norad"], "name": sd["name"],
                                 "min_elevation": t.conf.get("min_elevation", 10)})
        if not pred or not getattr(pred, "available", False) or not sats:
            return []
        return pred.upcoming(sats, hours=hours, limit=limit)
