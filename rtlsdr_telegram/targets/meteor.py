"""Hedef 13 — Meteor-M hava uydusu (LRPT, 137 MHz).

Araç: SatDump (live kipi). Her görünür geçişte SatDump'ı LRPT ardışık düzeniyle
çalıştırır; geçiş bitince ürün klasöründeki görüntüleri (PNG) toplar ve her birini
olay olarak gönderir. Geçiş zamanları TLE'den hesaplanır (satellites.py).

Not: NOAA'nın analog APT uyduları 2025'te kapatıldı; yalnızca Meteor-M hedeflenir.
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
from .base import TargetBase


class MeteorTarget(TargetBase):
    NAME = "Meteor-M Görüntü"
    CATEGORY = Category.UYDU
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 2, "dwell_s": 0, "period_s": 0,
        "min_elevation": 20, "gain": 42, "samplerate": 1024000,
        "pipeline": "meteor_m2-x_lrpt", "lookahead_h": 16,
        "band_label": "137 MHz Meteor-M LRPT",
        "satellites": [
            {"name": "METEOR-M2 3", "norad": 57166, "freq_mhz": 137.9, "pipeline": "meteor_m2-x_lrpt"},
            {"name": "METEOR-M2 4", "norad": 59051, "freq_mhz": 137.1, "pipeline": "meteor_m2-x_lrpt"},
        ],
        "max_images": 6,
    }

    def __init__(self, key, ctx):
        super().__init__(key, ctx)
        self.predictor = None  # main tarafından atanır

    def tools_available(self):
        ok = self.cfg.which("satdump") is not None
        return ok, ("" if ok else "satdump yok")

    # --------------------------------------------------- zamanlanmış pencere
    def next_window(self, now: float):
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
        self.log.info("Meteor geçişi: %s, max %.0f° irtifa, %.0f sn", sat["name"], p.max_elevation, p.duration_s)
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
        # yinelenenleri at, boyut filtrele
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
            self.log.info("Meteor geçişinde görüntü üretilemedi (%s)", sat["name"])
            ev = self.make_event(
                self.NAME, summary=f"{sat['name']} geçişi tamamlandı, görüntü alınamadı",
                body=("Geçiş dinlendi ancak çözülebilir LRPT görüntüsü üretilmedi "
                      "(düşük irtifa, zayıf sinyal veya anten yönü). "
                      f"Maksimum irtifa: {p.max_elevation:.0f}°."),
                freq_mhz=sat["freq_mhz"], priority=self.priority)
            self.emit(ev)
            return
        maxn = int(self.conf.get("max_images", 6))
        # tercihen 'corrected'/'rgb' içeren ürünleri öne al
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
            self.NAME, summary=f"{sat['name']} geçişi — {len(chosen)} görüntü (max {p.max_elevation:.0f}°)",
            body=(f"Uydu       : {sat['name']}\nFrekans    : {sat['freq_mhz']:.3f} MHz\n"
                  f"Maks. irtifa: {p.max_elevation:.0f}°\nGörüntü     : {len(chosen)} adet"),
            freq_mhz=sat["freq_mhz"], priority=self.priority, attachments=atts,
            duration_s=p.duration_s, time_utc=p.rise)
        self.emit(ev)
