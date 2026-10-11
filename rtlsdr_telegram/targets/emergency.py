"""Hedef 7 — Acil durum vericileri: 406 MHz (EPIRB/ELT/PLB) ve 121.5 MHz.

Yakalanınca ÖNCELİKLİ ALARM (kuyruğun önüne geçer, sesli bildirim).

Tam COSPAS-SARSAT 406 çözümü özel donanım/yazılım ister; burada güvenilir biçimde
ENERJİ TESPİTİ yapılır:
  - 406.0–406.1 MHz: rtl_power ile dar-bant tarama; taban gürültüsünün belirgin
    üzerinde bir patlama ALARM üretir (406 vericileri ~0.5 sn / 50 sn yayınlar).
  - 121.5 MHz: AM demodülasyon; sürekli yüksek seviye (ELT süpürme tonu) ALARM
    üretir ve doğrulama için kısa ses kaydı alınır.

Yanlış alarmı azaltmak için eşik yüksek tutulur ve tekrarlar belirli süre bastırılır.
Not: Bu bantları yalnızca dinlemek yasaldır; 406 MHz'de yayın yapmak yasaktır.
"""
from __future__ import annotations

import threading
import time

from ..events import Category, Attachment, PRIO_EMERGENCY
from .base import TargetBase


class EmergencyTarget(TargetBase):
    NAME = "Acil Verici"
    CATEGORY = Category.ACIL
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 0, "dwell_s": 30, "period_s": 120,
        "gain": 40,
        "watch_406": True, "band_406": [406.0, 406.1], "threshold_406_db": 15.0,
        "watch_121_5": True, "freq_121_5_mhz": 121.5, "threshold_121_5_dbfs": -35.0,
        "sustain_s": 2.0, "record_121_5": True, "suppress_repeat_s": 300,
        "band_label": "406 MHz / 121.5 MHz acil",
    }

    def tools_available(self):
        ok = self.sdr.bin_rtl_power is not None or self.sdr.bin_rtl_fm is not None
        return ok, ("" if ok else "rtl_power/rtl_fm yok")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        tasks = []
        if self.conf.get("watch_406", True) and self.sdr.bin_rtl_power:
            tasks.append("406")
        if self.conf.get("watch_121_5", True) and self.sdr.bin_rtl_fm:
            tasks.append("121")
        if not tasks:
            return
        share = duration_s / len(tasks)
        for t in tasks:
            if stop_event.is_set():
                break
            if t == "406":
                self._scan_406(stop_event, share)
            else:
                self._watch_121_5(stop_event, share)

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

        deadline = time.time() + secs
        while time.time() < deadline and not stop_event.is_set():
            rows.clear()
            try:
                proc = self.sdr.power_scan(start, end, 2000, integration="1",
                                           gain=self.conf.get("gain", 40), oneshot=True,
                                           log_path=self.cfg.log_dir / "emerg406.log")
            except Exception as e:
                self.log_error(f"406 tarama kurulamadı: {e}")
                return
            proc.on_line = on_line
            try:
                proc.start()
                t0 = time.time()
                while time.time() - t0 < 4 and proc.running and not stop_event.is_set():
                    stop_event.wait(0.3)
            finally:
                proc.stop()
            if rows:
                vals = [v for _, v in rows]
                med = sorted(vals)[len(vals) // 2]
                fpk, vpk = max(rows, key=lambda x: x[1])
                if vpk - med >= thr:
                    self._alarm("406", round(fpk / 1e6, 4), f"+{vpk - med:.0f} dB taban üstü", vpk)
            stop_event.wait(1.0)

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
            self.log_error(f"121.5 izleme başlatılamadı: {e}")
            return
        bps = rate * 2
        above = 0.0
        deadline = time.time() + secs
        try:
            while time.time() < deadline and not stop_event.is_set() and proc.running:
                block = proc.read_stdout_bytes(int(bps * 0.2))
                if not block:
                    time.sleep(0.02)
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

    def _alarm_121(self, freq_hz, lvl, stop_event):
        atts = []
        dur = 0.0
        if self.conf.get("record_121_5", True):
            segs = self.audio.record_window(freq_hz, 10, stop_event, mode="am", audio_rate=16000,
                                            threshold_dbfs=self.conf.get("threshold_121_5_dbfs", -35.0) - 5,
                                            hangover_s=2.0, min_segment_s=0.5, max_segment_s=15,
                                            gain=self.conf.get("gain", 40), prefix="emerg121")
            for s in segs:
                atts.append(Attachment("voice", s.final_path, caption="121.5 MHz kaydı"))
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
            etype = "ACİL 406 MHz"
            label = "EPIRB/ELT/PLB acil durum vericisi (406 MHz)"
            desc = ("406 MHz bandında güçlü patlama tespit edildi. Bu bant yalnızca EPIRB "
                    "(gemi), ELT (uçak) ve PLB (kişisel) acil durum vericilerine ayrılmıştır. "
                    "Gerçek bir acil durum olabilir — doğrulayın ve gerekirse yetkilileri arayın (AKUB/112).")
        else:
            etype = "ACİL 121.5 MHz"
            label = "121.5 MHz acil/ELT tonu"
            desc = ("121.5 MHz'de sürekli güçlü sinyal (ELT süpürme tonu olabilir) tespit edildi. "
                    "Ekli kaydı dinleyerek doğrulayın.")
        ev = self.make_event(
            etype, summary=f"⚠️ {label} — {freq_mhz:.3f} MHz",
            body=f"<b>{label}</b>\n{desc}", freq_mhz=freq_mhz,
            signal=signal_txt, signal_value=sig_val, priority=PRIO_EMERGENCY,
            attachments=attachments or [], duration_s=duration,
            dedup_key=f"emerg-{kind}-{int(now // supp)}")
        self.emit(ev)
