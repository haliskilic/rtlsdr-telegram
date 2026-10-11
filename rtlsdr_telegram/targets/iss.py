"""Hedef 14 — ISS (Uluslararası Uzay İstasyonu, 145.800/145.825 MHz).

Geçiş penceresinde (TLE'den hesaplanır) seçilen kipte çalışır:
  - voice (varsayılan): 145.800 MHz FM ses kaydı → ses + transkripsiyon.
  - sstv: 145.800 MHz FM kaydı + SSTV çözümü (harici çözücü komutu tanımlıysa).
  - aprs: 145.825 MHz FM paket (ISS dijipiter) → multimon-ng/aprslib.

ISS sesi/SSTV'si yalnızca etkinlik zamanlarında yayınlanır; geçişte sinyal yoksa
kısa "geçiş dinlendi, yayın yok" notu üretilir.
"""
from __future__ import annotations

import glob
import os
import threading
import time
from pathlib import Path

from ..events import Category, Attachment
from .base import TargetBase, audio_attachment


class ISSTarget(TargetBase):
    NAME = "ISS"
    CATEGORY = Category.UYDU
    CLASS = "pass"
    DEFAULTS = {
        "enabled": True, "priority": 2, "dwell_s": 0, "period_s": 0,
        "norad": 25544, "min_elevation": 15, "lookahead_h": 12,
        "mode": "voice", "voice_freq_mhz": 145.800, "aprs_freq_mhz": 145.825,
        "gain": "auto", "threshold_dbfs": -42.0, "transcribe_language": "en",
        "sstv_decoder_cmd": "", "band_label": "145.800/145.825 MHz ISS",
    }

    def __init__(self, key, ctx):
        super().__init__(key, ctx)
        self.predictor = None

    def tools_available(self):
        ok = self.sdr.bin_rtl_fm is not None
        return ok, ("" if ok else "rtl_fm yok")

    def next_window(self, now: float):
        c = getattr(self, "_winc", None)
        if c and (now - c[0]) < 120 and (c[1] is None or c[1][1] > now):
            return c[1]
        win = self._compute_window(now)
        self._winc = (now, win)
        return win

    def _compute_window(self, now: float):
        if not self.predictor or not self.predictor.available:
            return None
        p = self.predictor.next_pass(self.conf.get("norad", 25544), "ISS",
                                     hours=self.conf.get("lookahead_h", 12),
                                     min_elev=self.conf.get("min_elevation", 15))
        if not p:
            return None
        self._pending = p
        return p.rise.timestamp(), p.set.timestamp()

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        p = getattr(self, "_pending", None)
        if not p:
            self.next_window(time.time())
            p = getattr(self, "_pending", None)
            if not p:
                return
        mode = self.conf.get("mode", "voice")
        self.log.info("ISS geçişi: max %.0f° irtifa, %.0f sn, kip=%s", p.max_elevation, p.duration_s, mode)
        if mode == "aprs":
            self._run_aprs(stop_event, duration_s, p)
        else:
            self._run_voice(stop_event, duration_s, p, sstv=(mode == "sstv"))
        self._pending = None

    def _run_voice(self, stop_event, duration_s, p, sstv=False):
        freq_hz = int(self.conf.get("voice_freq_mhz", 145.8) * 1e6)
        segs = self.audio.record_window(
            freq_hz, duration_s, stop_event, mode="fm", audio_rate=16000,
            threshold_dbfs=float(self.conf.get("threshold_dbfs", -42.0)),
            hangover_s=3.0, min_segment_s=1.0, max_segment_s=max(60, p.duration_s),
            gain=self.conf.get("gain", "auto"), channel="ISS 145.800", prefix="iss",
            require_dynamics=False)
        if not segs:
            self._no_signal(p)
            return
        for seg in segs:
            atts = [audio_attachment(seg.final_path, caption="ISS 145.800 MHz")]
            images = self._try_sstv(seg.final_path) if sstv else []
            for img in images:
                atts.append(Attachment("photo", img, caption="ISS SSTV"))
            rec_id = self.st.add_recording(seg.start_utc.timestamp(), self.KEY, 145.800, "ISS",
                                           seg.duration_s, seg.final_path, f"{seg.peak_dbfs:.1f} dBFS", None)
            ev = self.make_event(
                "ISS SSTV/Ses" if sstv else "ISS Ses",
                summary=f"ISS geçişi — {seg.duration_s:.0f} sn yayın (max {p.max_elevation:.0f}°)"
                        + (f", {len(images)} SSTV görüntüsü" if images else ""),
                body=f"Maks. irtifa: {p.max_elevation:.0f}°\nTepe seviye : {seg.peak_dbfs:.1f} dBFS",
                freq_mhz=145.800, signal=f"{seg.peak_dbfs:.1f} dBFS (tepe)", signal_value=seg.peak_dbfs,
                duration_s=seg.duration_s, attachments=atts, priority=self.priority, time_utc=seg.start_utc)
            ev.transcript_status = "pending"
            ev.transcription_language = self.conf.get("transcribe_language", "en")
            ev.extra["recording_id"] = rec_id
            self.emit(ev)

    def _try_sstv(self, wav_path: str) -> list[str]:
        cmd_tmpl = self.conf.get("sstv_decoder_cmd", "")
        if not cmd_tmpl:
            return []
        outdir = Path(self.cfg.data_dir / "tmp" / f"sstv_{int(time.time())}")
        outdir.mkdir(parents=True, exist_ok=True)
        cmd = cmd_tmpl.format(wav=wav_path, outdir=str(outdir))
        try:
            import subprocess
            subprocess.run(cmd, shell=True, timeout=120, capture_output=True)
        except (subprocess.SubprocessError, OSError) as e:
            self.log.warning("SSTV çözücü hatası: %s", e)
            return []
        imgs = []
        dst_dir = self.cfg.recordings_dir / "sstv"
        dst_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for img in sorted(glob.glob(str(outdir / "*.png")) + glob.glob(str(outdir / "*.jpg"))):
            dst = dst_dir / os.path.basename(img)
            try:
                shutil.copy2(img, dst)
                imgs.append(str(dst))
            except OSError:
                pass
        shutil.rmtree(outdir, ignore_errors=True)
        return imgs

    def _run_aprs(self, stop_event, duration_s, p):
        from .aprs import APRSTarget
        freq_hz = int(self.conf.get("aprs_freq_mhz", 145.825) * 1e6)
        rate = 22050
        rtl = self.sdr.rtl_fm_cmd(freq_hz, mode="fm", sample_rate=rate, resample=rate,
                                  gain=self.conf.get("gain", "auto"))
        mm = self.cfg.which("multimon-ng")
        if not mm:
            self._no_signal(p)
            return
        pipeline = " ".join("'" + str(x).replace("'", "'\\''") + "'" if " " in str(x) else str(x) for x in rtl)
        pipeline += f" | {mm} -t raw -a AFSK1200 -A -"
        count = {"n": 0}

        def on_line(line):
            if "APRS:" in line:
                count["n"] += 1
                frame = line.split("APRS:", 1)[1].strip()
                src = frame.split(">")[0] if ">" in frame else "?"
                ev = self.make_event("ISS Paket", summary=f"ISS dijipiter paketi: {src}",
                                     body=f"<code>{frame[:200]}</code>", freq_mhz=145.825,
                                     priority=self.priority)
                self.emit(ev)
        self.run_tool_lines(["bash", "-c", pipeline], stop_event, duration_s, on_line,
                            name="iss-aprs", log_name="iss")
        if count["n"] == 0:
            self._no_signal(p)

    def _no_signal(self, p):
        ev = self.make_event(
            "ISS Geçiş", summary=f"ISS geçişi dinlendi, yayın yok (max {p.max_elevation:.0f}°)",
            body=("ISS geçişi penceresi dinlendi ancak sinyal yakalanmadı. ISS sesi/SSTV'si "
                  "yalnızca planlı etkinliklerde yayınlanır."),
            freq_mhz=145.800, priority=6, time_utc=p.rise, duration_s=p.duration_s)
        self.emit(ev)
