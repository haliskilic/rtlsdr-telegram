"""Target 7 — Distress beacons: 406 MHz (EPIRB/ELT/PLB) and 121.5 MHz.

A detection raises a PRIORITY ALARM (jumps the queue, audible notification).

Full COSPAS-SARSAT 406 decoding needs dedicated hardware/software; here a
reliable ENERGY DETECTION is performed:
  - 406.0–406.1 MHz: continuous narrow-band rtl_power sweep with per-bin max
    hold; a burst clearly above the noise floor raises the alarm (406 beacons
    transmit ~0.5 s every 50 s).
  - 121.5 MHz: AM demodulation; a sustained strong level (ELT sweep tone)
    raises the alarm and a short recording is attached for verification.

Thresholds are deliberately high to limit false alarms and repeats are
suppressed for a while. Note: receiving these bands is legal; transmitting on
406 MHz is not.
"""
from __future__ import annotations

import threading
import time

from ..events import Category, Attachment, PRIO_EMERGENCY
from ..i18n import t
from .base import TargetBase, audio_attachment


class EmergencyTarget(TargetBase):
    NAME_KEY = "emerg.name"
    BAND_KEY = "emerg.band"
    CATEGORY = Category.ACIL
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 0, "dwell_s": 35, "period_s": 240,
        "dwell_406_s": 25, "dwell_121_s": 10,
        "gain": 40,
        "watch_406": True, "band_406": [406.0, 406.1], "threshold_406_db": 15.0,
        "watch_121_5": True, "freq_121_5_mhz": 121.5, "threshold_121_5_dbfs": -35.0,
        "sustain_s": 2.0, "record_121_5": True, "suppress_repeat_s": 300,
    }

    def tools_available(self):
        ok = self.sdr.bin_rtl_power is not None or self.sdr.bin_rtl_fm is not None
        return ok, ("" if ok else "rtl_power/rtl_fm not found")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        tasks = []
        if self.conf.get("watch_406", True) and self.sdr.bin_rtl_power:
            tasks.append("406")
        if self.conf.get("watch_121_5", True) and self.sdr.bin_rtl_fm:
            tasks.append("121")
        if not tasks:
            return
        # 406 MHz beacons transmit 0.5 s every ~50 s; a continuous (not one-shot) sweep
        # raises the catch probability. Duration: dwell_406_s + dwell_121_s.
        d406 = float(self.conf.get("dwell_406_s", 25))
        d121 = float(self.conf.get("dwell_121_s", 10))
        total = d406 + d121 if ("406" in tasks and "121" in tasks) else duration_s
        scale = min(1.0, duration_s / total) if total > 0 else 1.0
        for task in tasks:
            if stop_event.is_set():
                break
            if task == "406":
                self._scan_406(stop_event, d406 * scale if "121" in tasks else duration_s)
            else:
                self._watch_121_5(stop_event, d121 * scale if "406" in tasks else duration_s)

    # ------------------------------------------------------------- 406 MHz
    def _scan_406(self, stop_event, secs):
        band = self.conf.get("band_406", [406.0, 406.1])
        start, end = int(band[0] * 1e6), int(band[1] * 1e6)
        thr = float(self.conf.get("threshold_406_db", 15.0))
        rows = []

        def on_line(line):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                return
            try:
                f_low = float(parts[2]); step = float(parts[4])
                vals = [float(x) for x in parts[6:] if x]
            except ValueError:
                return
            for i, v in enumerate(vals):
                rows.append((f_low + i * step, v))

        try:
            proc = self.sdr.power_scan(start, end, 2000, integration="1",
                                       gain=self.conf.get("gain", 40), oneshot=False,
                                       log_path=self.cfg.log_dir / "emerg406.log")
        except Exception as e:
            self.log_error(f"406 MHz sweep could not be started: {e}")
            return
        proc.on_line = on_line
        deadline = time.time() + secs
        try:
            proc.start()
            while time.time() < deadline and proc.running and not stop_event.is_set():
                stop_event.wait(0.5)
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass
        if not rows:
            return
        # per-bin max-hold so short bursts are not averaged away
        peak_by_f: dict[float, float] = {}
        for f, v in rows:
            if v > peak_by_f.get(f, -999):
                peak_by_f[f] = v
        vals = sorted(peak_by_f.values())
        med = vals[len(vals) // 2]
        fpk, vpk = max(peak_by_f.items(), key=lambda x: x[1])
        if vpk - med >= thr:
            self._alarm("406", round(fpk / 1e6, 4), t("common.above_floor_peak", db=f"{vpk - med:.0f}"), vpk)

    # ----------------------------------------------------------- 121.5 MHz
    def _watch_121_5(self, stop_event, secs):
        from ..audio import _rms_dbfs
        from ..proc import ManagedProcess
        freq = int(self.conf.get("freq_121_5_mhz", 121.5) * 1e6)
        thr = float(self.conf.get("threshold_121_5_dbfs", -35.0))
        sustain = float(self.conf.get("sustain_s", 2.0))
        rate = 16000
        cmd = self.sdr.rtl_fm_cmd(freq, mode="am", sample_rate=rate, resample=rate,
                                  gain=self.conf.get("gain", 40))
        proc = ManagedProcess(cmd, name="emerg121", text_stdout=False,
                              log_path=self.cfg.log_dir / "emerg121.log")
        try:
            proc.start()
        except Exception as e:
            self.log_error(f"121.5 MHz watch could not be started: {e}")
            return
        bps = rate * 2
        above = 0.0
        deadline = time.time() + secs
        try:
            while time.time() < deadline and not stop_event.is_set():
                block = proc.read_stdout_bytes(int(bps * 0.2), timeout=0.5)
                if block == b"":
                    break
                if block is None:
                    above = max(0.0, above - 0.2)
                    if not proc.running:
                        break
                    continue
                lvl = _rms_dbfs(block)
                if lvl >= thr:
                    above += 0.2
                    if above >= sustain:
                        proc.stop()
                        self._alarm_121(freq, lvl, stop_event)
                        return
                else:
                    above = max(0.0, above - 0.1)
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass

    def _alarm_121(self, freq_hz, lvl, stop_event):
        atts = []
        dur = 0.0
        if self.conf.get("record_121_5", True):
            segs = self.audio.record_window(freq_hz, 10, stop_event, mode="am", audio_rate=16000,
                                            threshold_dbfs=self.conf.get("threshold_121_5_dbfs", -35.0) - 5,
                                            hangover_s=2.0, min_segment_s=0.5, max_segment_s=15,
                                            gain=self.conf.get("gain", 40), prefix="emerg121",
                                            require_dynamics=False)
            for s in segs:
                atts.append(audio_attachment(s.final_path, caption=t("emerg.caption_121")))
                dur += s.duration_s
        self._alarm("121", round(freq_hz / 1e6, 4), f"{lvl:.1f} dBFS", lvl, attachments=atts, duration=dur)

    # ------------------------------------------------------------- alarm
    def _alarm(self, kind: str, freq_mhz: float, signal_txt: str, sig_val, attachments=None, duration=None):
        supp = float(self.conf.get("suppress_repeat_s", 300))
        state = self.st.registry_get("emerg_beacon", kind)
        now = time.time()
        if state and now - state["last_seen"] < supp:
            self.registry_touch("emerg_beacon", kind)
            return
        self.registry_touch("emerg_beacon", kind, {"freq": freq_mhz})
        if kind == "406":
            etype, label, desc = t("evt.emerg_406"), t("emerg.label_406"), t("emerg.desc_406")
        else:
            etype, label, desc = t("evt.emerg_121"), t("emerg.label_121"), t("emerg.desc_121")
        ev = self.make_event(
            etype, summary=f"⚠️ {label} — {freq_mhz:.3f} MHz",
            body=f"<b>{label}</b>\n{desc}", freq_mhz=freq_mhz,
            signal=signal_txt, signal_value=sig_val, priority=PRIO_EMERGENCY,
            attachments=attachments or [], duration_s=duration,
            dedup_key=f"emerg-{kind}-{int(now // supp)}")
        self.emit(ev)
