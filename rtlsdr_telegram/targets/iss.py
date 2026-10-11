"""Target 14 — ISS (International Space Station, 145.800/145.825 MHz).

During the TLE-computed pass window the selected mode runs:
  - voice (default): 145.800 MHz FM recording -> audio + transcript.
  - sstv: 145.800 MHz FM recording + SSTV decoding (if an external decoder is configured).
  - aprs: 145.825 MHz FM packets (ISS digipeater) -> multimon-ng/aprslib.

ISS voice/SSTV is only transmitted during events; a pass without a signal
produces a short "pass monitored, no transmission" note.
"""
from __future__ import annotations

import glob
import os
import threading
import time
from pathlib import Path

from ..events import Category, Attachment
from ..i18n import t
from ..proc import shell_pipeline
from .base import TargetBase, audio_attachment


class ISSTarget(TargetBase):
    NAME_KEY = "iss.name"
    BAND_KEY = "iss.band"
    CATEGORY = Category.UYDU
    CLASS = "pass"
    DEFAULTS = {
        "enabled": True, "priority": 2, "dwell_s": 0, "period_s": 0,
        "norad": 25544, "min_elevation": 15, "lookahead_h": 12,
        "mode": "voice", "voice_freq_mhz": 145.800, "aprs_freq_mhz": 145.825,
        "gain": "auto", "threshold_dbfs": -42.0, "transcribe_language": "en",
        "sstv_decoder_cmd": "",
    }

    def __init__(self, key, ctx):
        super().__init__(key, ctx)
        self.predictor = None

    def tools_available(self):
        ok = self.sdr.bin_rtl_fm is not None
        return ok, ("" if ok else "rtl_fm not found")

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
            # bypass next_window(): its cache does not refresh _pending
            self._compute_window(time.time())
            p = getattr(self, "_pending", None)
            if not p:
                return
        set_ts = p.set.timestamp()
        key = int(set_ts)
        if key == getattr(self, "_done_key", None):
            self._pending = None
            self.pass_done_until(set_ts)
            return
        mode = self.conf.get("mode", "voice")
        self.log.info("ISS pass: max elevation %.0f°, %.0f s, mode=%s", p.max_elevation, p.duration_s, mode)
        started = time.time()
        if mode == "aprs":
            got = self._run_aprs(stop_event, duration_s, p)
        else:
            got = self._run_voice(stop_event, duration_s, p, sstv=(mode == "sstv"))
        ran_s = time.time() - started
        remaining = set_ts - time.time()
        if not got and remaining > 90:
            if stop_event.is_set():
                self.pass_retry_in(5)  # pre-empted by an ad-hoc scan: resume afterwards
                return
            if ran_s < 20 and getattr(self, "_retry_key", None) != key:
                # recorder/rtl_fm failed to start: one retry after a back-off
                self._retry_key = key
                self.pass_retry_in(45)
                return
        # one report per pass, then leave the dongle alone until the window ends
        self._done_key = key
        self._pending = None
        self.pass_done_until(set_ts)
        if not got:
            self._no_signal(p)

    def _run_voice(self, stop_event, duration_s, p, sstv=False) -> bool:
        freq_hz = int(self.conf.get("voice_freq_mhz", 145.8) * 1e6)
        segs = self.audio.record_window(
            freq_hz, duration_s, stop_event, mode="fm", audio_rate=16000,
            threshold_dbfs=float(self.conf.get("threshold_dbfs", -42.0)),
            hangover_s=3.0, min_segment_s=1.0, max_segment_s=max(60, p.duration_s),
            gain=self.conf.get("gain", "auto"), channel="ISS 145.800", prefix="iss",
            require_dynamics=False)
        if not segs:
            return False
        for seg in segs:
            atts = [audio_attachment(seg.final_path, caption=t("iss.caption"))]
            images = self._try_sstv(seg.final_path) if sstv else []
            for img in images:
                atts.append(Attachment("photo", img, caption=t("iss.sstv_caption")))
            rec_id = self.st.add_recording(seg.start_utc.timestamp(), self.KEY, 145.800, "ISS",
                                           seg.duration_s, seg.final_path, f"{seg.peak_dbfs:.1f} dBFS", None)
            ev = self.make_event(
                t("evt.iss_sstv") if sstv else t("evt.iss_voice"),
                summary=t("iss.summary", s=f"{seg.duration_s:.0f}", el=f"{p.max_elevation:.0f}")
                        + (t("iss.sstv_count", n=len(images)) if images else ""),
                body=f"{t('iss.max_el')}: {p.max_elevation:.0f}°\n{t('iss.peak')}: {seg.peak_dbfs:.1f} dBFS",
                freq_mhz=145.800, signal=t("common.peak_dbfs", v=f"{seg.peak_dbfs:.1f}"), signal_value=seg.peak_dbfs,
                duration_s=seg.duration_s, attachments=atts, priority=self.priority, time_utc=seg.start_utc)
            ev.transcript_status = "pending"
            ev.transcription_language = self.conf.get("transcribe_language", "en")
            ev.extra["recording_id"] = rec_id
            self.emit(ev)
        return True

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
            self.log.warning("SSTV decoder error: %s", e)
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

    def _run_aprs(self, stop_event, duration_s, p) -> bool:
        from .aprs import APRSTarget
        freq_hz = int(self.conf.get("aprs_freq_mhz", 145.825) * 1e6)
        rate = 22050
        rtl = self.sdr.rtl_fm_cmd(freq_hz, mode="fm", sample_rate=rate, resample=rate,
                                  gain=self.conf.get("gain", "auto"))
        mm = self.cfg.which("multimon-ng")
        if not mm:
            return False
        pipeline = " ".join("'" + str(x).replace("'", "'\\''") + "'" if " " in str(x) else str(x) for x in rtl)
        pipeline += f" | {mm} -t raw -a AFSK1200 -A -"
        count = {"n": 0}

        def on_line(line):
            if "APRS:" in line:
                count["n"] += 1
                frame = line.split("APRS:", 1)[1].strip()
                src = frame.split(">")[0] if ">" in frame else "?"
                ev = self.make_event(t("evt.iss_packet"), summary=t("iss.packet_summary", src=src),
                                     body=f"<code>{frame[:200]}</code>", freq_mhz=145.825,
                                     priority=self.priority)
                self.emit(ev)
        self.run_tool_lines(shell_pipeline(pipeline), stop_event, duration_s, on_line,
                            name="iss-aprs", log_name="iss")
        return count["n"] > 0

    def _no_signal(self, p):
        ev = self.make_event(
            t("evt.iss_pass"), summary=t("iss.no_signal_summary", el=f"{p.max_elevation:.0f}"),
            body=t("iss.no_signal_body"),
            freq_mhz=145.800, priority=6, time_utc=p.rise, duration_s=p.duration_s)
        self.emit(ev)
