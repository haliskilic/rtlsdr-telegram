"""Hedef 4 — Meteoroloji balonları (radyosonda, 400–406 MHz).

İki çalışma kipi:
  (a) Tespit (yerleşik): rtl_power ile 400–406 MHz taranır, dar-bant güçlü
      taşıyıcılar radyosonda adayı olarak bildirilir. Dongle gerektirir.
  (b) Telemetri (radiosonde_auto_rx entegrasyonu): auto_rx ayrı olarak kuruluysa
      ürettiği `*_sonde.log` CSV dosyaları izlenir; kalkış (ilk kare), irtifa,
      patlama (tepe sonrası hızlı alçalma) ve tahmini düşüş noktası bildirilir.
      Bu kip dongle'ı auto_rx kullandığı için ayrı çalışır (fırsatçı okuma).

Tam çözümleme radiosonde_auto_rx gerektirir (kaynaktan kurulur); yerleşik kip
yalnızca "balon olabilir" uyarısı verir. Seçim config.auto_rx.* iledir.
"""
from __future__ import annotations

import csv
import glob
import math
import os
import threading
import time
from pathlib import Path

from ..events import Category, PRIO_IMPORTANT
from ..geo import haversine_km, bearing_deg, compass_tr
from .base import TargetBase


class RadiosondeTarget(TargetBase):
    NAME = "Radyosonda"
    CATEGORY = Category.METEOROLOJI
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 45, "period_s": 600,
        "scan_start_mhz": 400.0, "scan_end_mhz": 406.0, "bin_khz": 5,
        "detect_threshold_db": 12.0, "gain": "auto",
        "band_label": "400–406 MHz radyosonda",
        "auto_rx": {"enabled": False, "log_dir": "", "manage": False, "descent_rate_landing": True},
    }

    def tools_available(self):
        if self.conf.get("auto_rx", {}).get("enabled"):
            return True, ""
        ok = self.sdr.bin_rtl_power is not None
        return ok, ("" if ok else "rtl_power yok")

    def needs_device(self) -> bool:
        # auto_rx telemetri kipinde dongle'ı auto_rx tutar; biz yalnız log okuruz
        return not self.conf.get("auto_rx", {}).get("enabled", False)

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        ar = self.conf.get("auto_rx", {})
        if ar.get("enabled") and ar.get("log_dir"):
            self._ingest_auto_rx(stop_event, duration_s)
        else:
            self._detect_scan(stop_event, duration_s)

    # ------------------------------------------------------- (a) tespit kipi
    def _detect_scan(self, stop_event, secs):
        if not self.sdr.bin_rtl_power:
            return
        start = int(self.conf.get("scan_start_mhz", 400.0) * 1e6)
        end = int(self.conf.get("scan_end_mhz", 406.0) * 1e6)
        binhz = int(self.conf.get("bin_khz", 5) * 1000)
        thr = float(self.conf.get("detect_threshold_db", 12.0))
        rows: list[tuple[float, float]] = []  # (freq_hz, dB)

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
            proc = self.sdr.power_scan(start, end, binhz, integration="1", gain=self.conf.get("gain", "auto"),
                                       oneshot=True, log_path=self.cfg.log_dir / "sonde_scan.log")
        except Exception as e:
            self.log_error(f"rtl_power kurulamadı: {e}")
            return
        proc.on_line = on_line
        try:
            proc.start()
            deadline = time.time() + min(secs, 20)
            while time.time() < deadline and proc.running and not stop_event.is_set():
                stop_event.wait(0.5)
        finally:
            proc.stop()
        if not rows:
            return
        vals = [v for _, v in rows]
        med = sorted(vals)[len(vals) // 2]
        peaks = [(f, v) for f, v in rows if v - med >= thr]
        peaks.sort(key=lambda x: -x[1])
        reported = set()
        for f_hz, v in peaks[:3]:
            f_mhz = round(f_hz / 1e6, 3)
            bucket = round(f_mhz, 2)
            if bucket in reported:
                continue
            reported.add(bucket)
            is_new, _, _ = self.registry_touch("sonde_carrier", f"{bucket:.2f}", {"db": round(v - med, 1)})
            ev = self.make_event(
                "Radyosonda Taşıyıcı (aday)",
                summary=f"{f_mhz:.3f} MHz'de güçlü taşıyıcı (+{v - med:.0f} dB) — radyosonda olabilir",
                body=("400–406 MHz tespit taramasında güçlü dar-bant taşıyıcı bulundu. "
                      "Tam çözümleme (seri no, konum, irtifa) için radiosonde_auto_rx'i etkinleştirin "
                      "(config: targets.radiosonde.auto_rx.enabled)."),
                freq_mhz=f_mhz, signal=f"+{v - med:.0f} dB taban üstü", signal_value=v,
                priority=(self.priority if not is_new else PRIO_IMPORTANT),
                dedup_key=f"sonde-carrier-{bucket:.2f}")
            self.emit(ev)

    # --------------------------------------------- (b) auto_rx telemetri kipi
    def _ingest_auto_rx(self, stop_event, secs):
        log_dir = self.cfg.resolve(self.conf["auto_rx"]["log_dir"])
        deadline = time.time() + secs
        while time.time() < deadline and not stop_event.is_set():
            for path in sorted(glob.glob(str(log_dir / "*_sonde.log"))):
                self._process_sonde_log(Path(path))
            stop_event.wait(5)

    def _process_sonde_log(self, path: Path):
        try:
            rows = list(csv.DictReader(path.read_text().splitlines()))
        except (OSError, csv.Error):
            return
        if not rows:
            return
        last = rows[-1]
        serial = last.get("serial") or path.stem
        try:
            lat = float(last.get("lat", "nan")); lon = float(last.get("lon", "nan"))
            alt = float(last.get("alt", "nan")); vv = float(last.get("vel_v", "0") or 0)
        except ValueError:
            return
        if math.isnan(lat) or math.isnan(lon):
            return
        state = self.st.registry_get("sonde", serial)
        peak_alt = (state or {}).get("data", {}).get("peak_alt", 0) if state else 0
        peak_alt = max(peak_alt, alt if not math.isnan(alt) else 0)
        phase = "yükseliş" if vv > 1 else ("alçalış" if vv < -2 else "sabit")
        burst = (alt < peak_alt - 500) and peak_alt > 12000
        self.registry_touch("sonde", serial, {"peak_alt": peak_alt, "last_alt": alt, "phase": phase})

        slat = self.cfg.get("station.lat"); slon = self.cfg.get("station.lon")
        dist = haversine_km(slat, slon, lat, lon) if slat is not None else None
        loc = f"{lat:.4f}, {lon:.4f}"
        if dist is not None:
            loc += f" ({dist:.1f} km {compass_tr(bearing_deg(slat, slon, lat, lon))})"

        # olay türünü faza göre belirle (her faz değişiminde bir bildirim)
        last_phase = (state or {}).get("data", {}).get("reported_phase") if state else None
        etype = None
        if last_phase is None:
            etype = "Radyosonda Kalkış"
        elif burst and last_phase != "patlama":
            etype = "Radyosonda Patlama"
            phase = "patlama"
        elif phase == "alçalış" and last_phase not in ("alçalış", "patlama"):
            etype = "Radyosonda Alçalış"
        if etype is None:
            return
        data = (self.st.registry_get("sonde", serial) or {}).get("data", {})
        data["reported_phase"] = phase
        self.st.registry_set_data("sonde", serial, data)

        body = [f"Seri no    : {serial}", f"İrtifa     : {alt:.0f} m (tepe {peak_alt:.0f} m)",
                f"Dikey hız  : {vv:+.1f} m/s", f"Faz        : {phase}"]
        pred = ""
        if burst or phase in ("alçalış", "patlama"):
            pred = self._predict_landing(lat, lon, alt, last)
            if pred:
                body.append(f"Tahmini düşüş: {pred}")
        ev = self.make_event(
            etype, summary=f"{serial} — {phase}, {alt:.0f} m" + (f", {dist:.0f} km" if dist else ""),
            body="\n".join(body), freq_mhz=float(last.get("freq_mhz", 0) or 0) or None,
            lat=lat, lon=lon, location_text=loc, priority=PRIO_IMPORTANT,
            dedup_key=f"sonde-{serial}-{phase}")
        self.emit(ev)

    @staticmethod
    def _predict_landing(lat, lon, alt, row) -> str:
        """Basit sürüklenme tahmini: mevcut yatay hız ve alçalma hızına göre."""
        try:
            vv = float(row.get("vel_v", "0") or 0)
            vh = float(row.get("vel_h", "0") or 0)
            heading = float(row.get("heading", "0") or 0)
        except ValueError:
            return ""
        if vv >= -1 or alt <= 0:
            return ""
        t = alt / abs(vv)  # kabaca iniş süresi (s)
        drift = vh * t  # yatay sürüklenme (m)
        # basit düz-dünya izdüşümü
        d_deg = drift / 111000.0
        rad = math.radians(heading)
        nlat = lat + d_deg * math.cos(rad)
        nlon = lon + d_deg * math.sin(rad) / max(0.1, math.cos(math.radians(lat)))
        return f"≈ {nlat:.4f}, {nlon:.4f} (~{t/60:.0f} dk sonra)"
