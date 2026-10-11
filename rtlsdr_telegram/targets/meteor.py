"""Target 13 — Meteor-M weather satellite (LRPT, 137 MHz).

Tool: SatDump (live mode). On every visible pass SatDump runs the LRPT
pipeline; when the pass ends the product images (PNG) are collected and sent
as one event. Pass times come from TLE data (satellites.py).

Note: NOAA's analog APT satellites were switched off in 2025; only Meteor-M is
targeted.
"""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..events import Category, Attachment
from ..i18n import t
from .base import TargetBase


class MeteorTarget(TargetBase):
    NAME_KEY = "meteor.name"
    BAND_KEY = "meteor.band"
    CATEGORY = Category.UYDU
    CLASS = "pass"
    DEFAULTS = {
        "enabled": True, "priority": 2, "dwell_s": 0, "period_s": 0,
        "min_elevation": 20, "gain": 42, "samplerate": 1024000,
        "pipeline": "meteor_m2-x_lrpt", "lookahead_h": 16,
        "satellites": [
            {"name": "METEOR-M2 3", "norad": 57166, "freq_mhz": 137.9, "pipeline": "meteor_m2-x_lrpt"},
            {"name": "METEOR-M2 4", "norad": 59051, "freq_mhz": 137.1, "pipeline": "meteor_m2-x_lrpt_80k"},
        ],
        "max_images": 6,
    }

    def __init__(self, key, ctx):
        super().__init__(key, ctx)
        self.predictor = None  # assigned by the application

    def tools_available(self):
        ok = self.cfg.which("satdump") is not None
        return ok, ("" if ok else "satdump not found")

    # --------------------------------------------------- scheduled window
    def next_window(self, now: float):
        # cache the window briefly (the scheduler asks every loop)
        c = getattr(self, "_winc", None)
        if c and (now - c[0]) < 120 and (c[1] is None or c[1][1] > now):
            return c[1]
        win = self._compute_window(now)
        self._winc = (now, win)
        return win

    def _compute_window(self, now: float):
        if not self.predictor or not self.predictor.available:
            return None
        best = None
        for sat in self.conf.get("satellites", []):
            p = self.predictor.next_pass(sat["norad"], sat["name"],
                                         hours=self.conf.get("lookahead_h", 16),
                                         min_elev=self.conf.get("min_elevation", 20))
            if p and (best is None or p.rise < best[0].rise):
                best = (p, sat)
        if not best:
            return None
        p, sat = best
        self._pending = (p, sat)
        return p.rise.timestamp(), p.set.timestamp()

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        pending = getattr(self, "_pending", None)
        if not pending:
            w = self.next_window(time.time())
            pending = getattr(self, "_pending", None)
            if not pending:
                return
        p, sat = pending
        self._run_pass(p, sat, stop_event, duration_s)
        self._pending = None

    def _run_pass(self, p, sat, stop_event, duration_s):
        binary = self.cfg.which("satdump")
        outdir = Path(tempfile.mkdtemp(prefix="meteor_", dir=str(self.cfg.data_dir / "tmp")))
        freq_hz = int(sat["freq_mhz"] * 1e6)
        sr = int(self.conf.get("samplerate", 1024000))
        timeout = int(min(duration_s, max(60, p.duration_s)))
        cmd = [binary, "live", sat.get("pipeline", self.conf.get("pipeline")), str(outdir),
               "--source", "rtlsdr", "--samplerate", str(sr), "--frequency", str(freq_hz),
               "--gain", str(self.conf.get("gain", 42)), "--timeout", str(timeout)]
        if self.sdr.ppm:
            cmd += ["--ppm_correction", str(self.sdr.ppm)]
        self.log.info("Meteor pass: %s, max elevation %.0f°, %.0f s", sat["name"], p.max_elevation, p.duration_s)
        rc = self.run_tool_lines(cmd, stop_event, timeout + 15, lambda l: None,
                                 name="satdump", log_name="satdump")
        self._collect(outdir, sat, p)
        try:
            shutil.rmtree(outdir, ignore_errors=True)
        except OSError:
            pass

    def _collect(self, outdir: Path, sat, p):
        imgs = []
        for ext in ("*.png", "**/*.png"):
            imgs.extend(glob.glob(str(outdir / ext), recursive=True))
        # drop duplicates, filter by size
        seen = set()
        uniq = []
        for img in sorted(imgs):
            name = os.path.basename(img)
            if name in seen:
                continue
            seen.add(name)
            try:
                if os.path.getsize(img) < 2048:
                    continue
            except OSError:
                continue
            uniq.append(img)
        if not uniq:
            self.log.info("Meteor pass produced no image (%s)", sat["name"])
            ev = self.make_event(
                self.display_name(), summary=t("meteor.no_image_summary", sat=sat["name"]),
                body=t("meteor.no_image_body", el=f"{p.max_elevation:.0f}"),
                freq_mhz=sat["freq_mhz"], priority=self.priority)
            self.emit(ev)
            return
        maxn = int(self.conf.get("max_images", 6))
        # prefer 'corrected'/'rgb' products
        uniq.sort(key=lambda s: (("corrected" not in s.lower()), ("221" not in s and "rgb" not in s.lower()), s))
        chosen = uniq[:maxn]
        kept_dir = self.cfg.recordings_dir / "meteor"
        kept_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M")
        atts = []
        for i, img in enumerate(chosen):
            dst = kept_dir / f"{sat['name'].replace(' ', '_')}_{stamp}_{i}_{os.path.basename(img)}"
            try:
                shutil.copy2(img, dst)
            except OSError:
                dst = Path(img)
            atts.append(Attachment("photo", str(dst), caption=f"{sat['name']} — {os.path.basename(img)}"))
        ev = self.make_event(
            self.display_name(), summary=t("meteor.summary", sat=sat["name"], n=len(chosen), el=f"{p.max_elevation:.0f}"),
            body=(f"{t('meteor.satellite')}: {sat['name']}\n{t('meteor.frequency')}: {sat['freq_mhz']:.3f} MHz\n"
                  f"{t('meteor.max_el')}: {p.max_elevation:.0f}°\n{t('meteor.images')}: {t('meteor.images_n', n=len(chosen))}"),
            freq_mhz=sat["freq_mhz"], priority=self.priority, attachments=atts,
            duration_s=p.duration_s, time_utc=p.rise)
        self.emit(ev)
