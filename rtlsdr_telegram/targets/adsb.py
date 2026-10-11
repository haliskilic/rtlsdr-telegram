"""Hedef 1 — Uçak takibi (ADS-B, 1090 MHz).

Araç: readsb (dump1090 uyumlu). readsb'yi JSON yazma kipinde çalıştırıp
aircraft.json dosyasını periyodik okuruz. Çağrı kodu, konum, irtifa, hız;
alçak uçuş ve acil squawk (7500/7600/7700) tespiti yapılır.

readsb'yi seçtik: bakımı sürenlerden, Debian deposunda var, düşük CPU'da çalışır
ve dump1090 ile aynı JSON biçimini üretir (dump1090 varsa o da kullanılabilir).
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from ..events import Category, PRIO_EMERGENCY, PRIO_IMPORTANT
from ..geo import haversine_km, bearing_deg, compass_tr
from .base import TargetBase

SQUAWK_EMERGENCY = {
    "7500": "Uçak kaçırma (hijack)",
    "7600": "Telsiz arızası",
    "7700": "Genel acil durum",
}


class ADSBTarget(TargetBase):
    NAME = "ADS-B Uçak"
    CATEGORY = Category.HAVACILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 3, "dwell_s": 60, "period_s": 180,
        "freq_mhz": 1090.0, "gain": "auto", "band_label": "1090 MHz ADS-B",
        "low_alt_ft": 3000, "report_new": True, "min_messages": 2,
        "tool": "readsb",
    }

    def tools_available(self):
        b = self.cfg.which(self.conf.get("tool", "readsb"), "readsb", "dump1090", "dump1090-fa")
        return (b is not None), ("" if b else "readsb/dump1090 bulunamadı")

    def _binary(self):
        return self.cfg.which(self.conf.get("tool", "readsb"), "readsb", "dump1090", "dump1090-fa")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        binary = self._binary()
        jdir = Path(tempfile.mkdtemp(prefix="adsb_", dir=str(self.cfg.data_dir / "tmp")))
        gain = self.conf.get("gain", "auto")
        name = Path(binary).name
        cmd = [binary, "--device-type", "rtlsdr", "--write-json", str(jdir),
               "--write-json-every", "1", "--quiet"]
        if "readsb" in name:
            cmd += ["--device", str(self.sdr.device_index)]
            if gain not in ("auto", "agc", None, -1):
                cmd += ["--gain", str(gain)]
            if self.sdr.ppm:
                cmd += ["--ppm", str(self.sdr.ppm)]
        else:  # dump1090
            cmd = [binary, "--write-json", str(jdir), "--write-json-every", "1", "--quiet"]
            if gain not in ("auto", "agc", None, -1):
                cmd += ["--gain", str(gain)]

        from ..proc import ManagedProcess
        proc = ManagedProcess(cmd, name="adsb", log_path=self.cfg.log_dir / "adsb.log")
        try:
            proc.start()
        except Exception as e:
            self.log_error(f"readsb başlatılamadı: {e}")
            return
        jfile = jdir / "aircraft.json"
        deadline = time.time() + duration_s
        seen_now: dict[str, dict] = {}
        try:
            while time.time() < deadline and not stop_event.is_set():
                if not proc.running:
                    break
                self._poll(jfile, seen_now)
                stop_event.wait(1.0)
        finally:
            proc.stop()
            self._cleanup(jdir)

    def _poll(self, jfile: Path, seen_now: dict) -> None:
        try:
            data = json.loads(jfile.read_text())
        except (OSError, ValueError):
            return
        station_lat = self.cfg.get("station.lat")
        station_lon = self.cfg.get("station.lon")
        low_alt = float(self.conf.get("low_alt_ft", 3000))
        min_msgs = int(self.conf.get("min_messages", 2))
        for ac in data.get("aircraft", []):
            hexid = (ac.get("hex") or "").strip().lower()
            if not hexid or ac.get("seen", 99) > 15:
                continue
            msgs = ac.get("messages", 0)
            flight = (ac.get("flight") or "").strip()
            squawk = str(ac.get("squawk") or "").strip()
            lat, lon = ac.get("lat"), ac.get("lon")
            alt = ac.get("alt_baro") if ac.get("alt_baro") not in (None, "ground") else ac.get("alt_geom")
            gs = ac.get("gs")
            track = ac.get("track")
            rssi = ac.get("rssi")

            is_new, first_seen, count = self.registry_touch(
                "aircraft", hexid, {"flight": flight or None, "squawk": squawk or None})

            # Acil durum squawk — her zaman bildir
            if squawk in SQUAWK_EMERGENCY and hexid not in self._emerg_sent(squawk):
                self._emit_emergency(hexid, flight, squawk, lat, lon, alt, gs, rssi, station_lat, station_lon)
                continue

            if not self.conf.get("report_new", True):
                continue
            if not is_new or msgs < min_msgs:
                continue
            self._emit_new(hexid, flight, squawk, lat, lon, alt, gs, track, rssi, station_lat, station_lon)

    _EMERG_CACHE: dict[str, set] = {}

    def _emerg_sent(self, squawk: str) -> set:
        return self._EMERG_CACHE.setdefault(squawk, set())

    def _emit_emergency(self, hexid, flight, squawk, lat, lon, alt, gs, rssi, slat, slon):
        self._emerg_sent(squawk).add(hexid)
        label = SQUAWK_EMERGENCY[squawk]
        loc = None
        if lat is not None and lon is not None and slat is not None:
            d = haversine_km(slat, slon, lat, lon)
            loc = f"{lat:.4f}, {lon:.4f} ({d:.1f} km {compass_tr(bearing_deg(slat, slon, lat, lon))})"
        body = [f"<b>Squawk {squawk}</b> — {label}",
                f"ICAO: <code>{hexid.upper()}</code>",
                f"Çağrı: {flight or '—'}"]
        if alt is not None:
            body.append(f"İrtifa: {alt} ft")
        if gs is not None:
            body.append(f"Yer hızı: {gs:.0f} kt")
        ev = self.make_event(
            f"ACİL {squawk} • Uçak", summary=f"{label}: {flight or hexid.upper()}",
            body="\n".join(body), freq_mhz=1090.0, lat=lat, lon=lon, location_text=loc,
            signal=(f"{rssi:.1f} dBFS" if rssi is not None else None),
            signal_value=rssi, priority=PRIO_EMERGENCY, dedup_key=f"adsb-emerg-{hexid}-{squawk}")
        ev.category = Category.ACIL
        self.emit(ev)

    def _emit_new(self, hexid, flight, squawk, lat, lon, alt, gs, track, rssi, slat, slon):
        loc = None
        dist = None
        if lat is not None and lon is not None and slat is not None:
            dist = haversine_km(slat, slon, lat, lon)
            loc = f"{lat:.4f}, {lon:.4f} ({dist:.1f} km {compass_tr(bearing_deg(slat, slon, lat, lon))})"
        low = alt is not None and isinstance(alt, (int, float)) and alt <= float(self.conf.get("low_alt_ft", 3000))
        body = [f"ICAO adresi: <code>{hexid.upper()}</code>",
                f"Çağrı kodu : {flight or '—'}"]
        if alt is not None:
            body.append(f"İrtifa     : {alt} ft" + ("  ⚠️ alçak uçuş" if low else ""))
        if gs is not None:
            body.append(f"Yer hızı   : {gs:.0f} kt")
        if track is not None:
            body.append(f"Yön        : {track:.0f}° ({compass_tr(track)})")
        if squawk:
            body.append(f"Squawk     : {squawk}")
        summary = f"Yeni uçak {flight or hexid.upper()}"
        if dist is not None:
            summary += f" — {dist:.0f} km"
        ev = self.make_event(
            self.NAME, summary=summary, body="\n".join(body), freq_mhz=1090.0,
            lat=lat, lon=lon, location_text=loc,
            signal=(f"{rssi:.1f} dBFS" if rssi is not None else None), signal_value=rssi,
            priority=(PRIO_IMPORTANT if low else self.priority), dedup_key=f"adsb-{hexid}")
        self.emit(ev)

    def _cleanup(self, jdir: Path):
        try:
            for f in jdir.glob("*"):
                f.unlink()
            jdir.rmdir()
        except OSError:
            pass
