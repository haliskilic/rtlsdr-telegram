"""Hedef 3 — Gemi takibi (AIS, 161.975 ve 162.025 MHz).

Araç: AIS-catcher (JSON tam çıktı kipi). Her iki AIS kanalını (A/B) aynı anda
alır. Gemi adı, MMSI, tip, konum, rota/hız çözümlenir. "Yeni gemi görüldü"
bildirimi kayıt defteri (registry) ile üretilir; statik mesajlar (tip 5/24)
gemi künyesini zenginleştirir.

AIS-catcher'ı seçtik: tek dongle ile iki kanalı birden (162 MHz merkez) alabilir,
yüksek yakalama oranı, JSON çıktısı. Yoksa rtl_ais'e düşülür (yalnız NMEA).
"""
from __future__ import annotations

import json
import threading

from ..events import Category
from ..geo import haversine_km, bearing_deg, compass_tr
from .base import TargetBase

# AIS gemi tipi kod -> kısa ad (ana gruplar)
SHIPTYPE = {
    30: "Balıkçı", 31: "Römorkör", 32: "Römorkör", 33: "Tarama/sualtı", 34: "Dalış",
    35: "Askeri", 36: "Yelkenli", 37: "Tekne", 50: "Pilot", 51: "Arama-kurtarma",
    52: "Römorkör", 53: "Liman hizmet", 54: "Kirlilikle mücadele", 55: "Kolluk",
    58: "Tıbbi", 60: "Yolcu", 61: "Yolcu", 62: "Yolcu", 63: "Yolcu", 64: "Yolcu",
    69: "Yolcu", 70: "Kargo", 71: "Kargo", 72: "Kargo", 73: "Kargo", 74: "Kargo",
    79: "Kargo", 80: "Tanker", 81: "Tanker", 82: "Tanker", 83: "Tanker", 84: "Tanker",
    89: "Tanker", 90: "Diğer",
}


def shiptype_name(code) -> str:
    if code is None:
        return "—"
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "—"
    if c in SHIPTYPE:
        return SHIPTYPE[c]
    base = (c // 10) * 10
    return SHIPTYPE.get(base, f"Tip {c}")


class AISTarget(TargetBase):
    NAME = "AIS Gemi"
    CATEGORY = Category.DENIZCILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 60, "period_s": 300,
        "gain": "auto", "sample_rate": 1536000,
        "band_label": "161.975 / 162.025 MHz AIS", "report_new": True,
        "report_position_every_s": 0,
    }

    def tools_available(self):
        if self.cfg.which("AIS-catcher"):
            return True, ""
        if self.cfg.which("rtl_ais"):
            return True, "(yalnız rtl_ais — sınırlı)"
        return False, "AIS-catcher / rtl_ais bulunamadı"

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if self.cfg.which("AIS-catcher"):
            self._run_catcher(stop_event, duration_s)
        elif self.cfg.which("rtl_ais"):
            self._run_rtl_ais(stop_event, duration_s)
        else:
            self.log.debug("AIS aracı yok")

    def _run_catcher(self, stop_event, secs):
        binary = self.cfg.which("AIS-catcher")
        gain = self.conf.get("gain", "auto")
        cmd = [binary, f"-d:{self.sdr.device_index}", "-o", "5", "-q"]
        if self.sdr.ppm:
            cmd += ["-p", str(self.sdr.ppm)]
        if gain not in ("auto", "agc", None, -1):
            cmd += ["-gr", "TUNER", str(gain)]
        self.run_tool_lines(cmd, stop_event, secs, self._on_json, name="AIS-catcher", log_name="aiscatcher")

    def _on_json(self, line: str):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        mmsi = d.get("mmsi")
        if not mmsi:
            return
        name = (d.get("shipname") or "").strip()
        callsign = (d.get("callsign") or "").strip()
        stype = d.get("shiptype")
        lat, lon = d.get("lat"), d.get("lon")
        speed = d.get("speed")
        course = d.get("course")
        dest = (d.get("destination") or "").strip()
        data = {"name": name or None, "callsign": callsign or None,
                "shiptype": stype if stype else None, "dest": dest or None}
        is_new, _, count = self.registry_touch("ship", str(mmsi), {k: v for k, v in data.items() if v})
        # yalnızca yeni gemi ya da ilk konumlu mesaj bildir
        if not is_new and not (self.conf.get("report_new", True) is False):
            if count > 1:
                return
        slat = self.cfg.get("station.lat")
        slon = self.cfg.get("station.lon")
        loc = None
        dist = None
        if lat is not None and lon is not None and slat is not None:
            dist = haversine_km(slat, slon, lat, lon)
            loc = f"{lat:.4f}, {lon:.4f} ({dist:.1f} km {compass_tr(bearing_deg(slat, slon, lat, lon))})"
        body = [f"MMSI       : <code>{mmsi}</code>",
                f"Gemi adı   : {name or '—'}",
                f"Çağrı işr. : {callsign or '—'}",
                f"Tip        : {shiptype_name(stype)}"]
        if speed is not None:
            body.append(f"Hız        : {speed} kn")
        if course is not None:
            body.append(f"Rota       : {course:.0f}° ({compass_tr(course)})")
        if dest:
            body.append(f"Varış      : {dest}")
        summary = f"Yeni gemi {name or mmsi}" + (f" — {dist:.0f} km" if dist is not None else "")
        ev = self.make_event(
            self.NAME, summary=summary, body="\n".join(body),
            freq_mhz=161.975, lat=lat, lon=lon, location_text=loc, dedup_key=f"ship-{mmsi}")
        self.emit(ev)

    def _run_rtl_ais(self, stop_event, secs):
        # rtl_ais yalnız ham NMEA üretir; burada yalnızca etkinlik varlığını not ederiz.
        binary = self.cfg.which("rtl_ais")
        cmd = [binary, "-d", str(self.sdr.device_index), "-n"]
        seen = {"count": 0}

        def on_line(line):
            if line.startswith("!AIVDM") or line.startswith("!AIVDO"):
                seen["count"] += 1
        self.run_tool_lines(cmd, stop_event, secs, on_line, name="rtl_ais", log_name="rtl_ais")
        if seen["count"]:
            ev = self.make_event(self.NAME, summary=f"{seen['count']} AIS cümlesi alındı (ham, çözülmedi)",
                                 body="rtl_ais ham NMEA üretti; tam çözümleme için AIS-catcher kurun.",
                                 freq_mhz=161.975)
            self.emit(ev)
