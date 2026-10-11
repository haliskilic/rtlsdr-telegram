"""Hedef 3 — Gemi takibi (AIS, 161.975 ve 162.025 MHz).

Araç: AIS-catcher (JSON tam çıktı, -o 5). İki AIS kanalını aynı anda alır.
Gemi adı, MMSI, tip, konum, rota/hız çözümlenir; gemi künyesi kayıt defterinde
birleştirilir (statik mesajlar adı sonradan tamamlar).

Sel koruması: Marmara gibi yoğun sularda yüzlerce gemi görülür. Varsayılan:
slot sonunda tek özet (en yakın gemiler listesi). Yalnız yeni VE yakın gemiler
ayrı mesaj alır. AIS SART/MOB/EPIRB-AIS (MMSI 970/972/974...) → ACİL alarm.
"""
from __future__ import annotations

import json
import threading
import time

from ..events import Category, PRIO_EMERGENCY, PRIO_IMPORTANT
from ..geo import haversine_km, bearing_deg, compass_tr
from .base import TargetBase

SHIPTYPE = {
    30: "Balıkçı", 31: "Römorkör", 32: "Römorkör", 33: "Tarama/sualtı", 34: "Dalış",
    35: "Askeri", 36: "Yelkenli", 37: "Tekne", 50: "Pilot", 51: "Arama-kurtarma",
    52: "Römorkör", 53: "Liman hizmet", 54: "Kirlilikle mücadele", 55: "Kolluk",
    58: "Tıbbi", 60: "Yolcu", 70: "Kargo", 80: "Tanker", 90: "Diğer",
}
SART_PREFIXES = {"970": "AIS-SART (arama-kurtarma vericisi)", "972": "MOB (denize adam düştü) vericisi",
                 "974": "EPIRB-AIS acil durum vericisi"}


def shiptype_name(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "—"
    return SHIPTYPE.get(c) or SHIPTYPE.get((c // 10) * 10, f"Tip {c}")


class AISTarget(TargetBase):
    NAME = "AIS Gemi"
    CATEGORY = Category.DENIZCILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 90, "period_s": 300,
        "gain": "auto", "band_label": "161.975 / 162.025 MHz AIS",
        "report_mode": "summary",       # summary | each
        "report_nearby_km": 5.0,        # yeni ve bu kadar yakın gemi ayrı mesaj
        "summary_list_max": 12,
        "sart_realert_min": 30,
    }

    def tools_available(self):
        if self.cfg.which("AIS-catcher"):
            return True, ""
        if self.cfg.which("rtl_ais"):
            return True, "(yalnız rtl_ais — sınırlı)"
        return False, "AIS-catcher / rtl_ais bulunamadı"

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        self._slot: dict[str, dict] = {}
        started = time.time()
        if self.cfg.which("AIS-catcher"):
            self._run_catcher(stop_event, duration_s)
        elif self.cfg.which("rtl_ais"):
            self._run_rtl_ais(stop_event, duration_s)
        else:
            return
        self._finish_slot(time.time() - started)

    def _run_catcher(self, stop_event, secs):
        binary = self.cfg.which("AIS-catcher")
        gain = self.conf.get("gain", "auto")
        cmd = [binary, f"-d:{self.sdr.device_index}", "-o", "5", "-q"]
        if self.sdr.ppm:
            cmd += ["-p", str(self.sdr.ppm)]
        if not self.sdr.is_auto_gain(gain):
            cmd += ["-gr", "TUNER", str(gain)]
        self.run_tool_lines(cmd, stop_event, secs, self._on_json, name="AIS-catcher", log_name="aiscatcher")

    # -------------------------------------------------------------- ayrıştırma
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
        mmsi = str(mmsi)
        rec = self._slot.get(mmsi)
        first = rec is None
        if first:
            rec = {"first": time.time(), "sent": False}
            self._slot[mmsi] = rec
        for k_src, k_dst in (("shipname", "name"), ("callsign", "callsign"), ("shiptype", "type"),
                             ("destination", "dest"), ("speed", "speed"), ("course", "course"),
                             ("lat", "lat"), ("lon", "lon"), ("status_text", "status")):
            v = d.get(k_src)
            if v not in (None, "", 0) or (k_src in ("speed", "course", "lat", "lon") and v is not None):
                if isinstance(v, str):
                    v = v.strip()
                if v != "":
                    rec[k_dst] = v
        slat = self.cfg.get("station.lat"); slon = self.cfg.get("station.lon")
        if rec.get("lat") is not None and rec.get("lon") is not None and slat is not None:
            try:
                rec["dist"] = haversine_km(slat, slon, float(rec["lat"]), float(rec["lon"]))
                rec["brg"] = bearing_deg(slat, slon, float(rec["lat"]), float(rec["lon"]))
            except (TypeError, ValueError):
                pass
        if first:
            is_new, _, _ = self.registry_touch("ship", mmsi, {"name": rec.get("name"), "type": rec.get("type")})
            rec["new"] = is_new
        else:
            # ad sonradan geldiyse kayıt defterini zenginleştir
            if rec.get("name"):
                self.registry_touch("ship", mmsi, {"name": rec.get("name"), "type": rec.get("type")})
        # Acil durum vericileri
        if mmsi[:3] in SART_PREFIXES:
            self._sart_alarm(mmsi, rec)
            return
        # Yeni + yakın gemi → ayrı mesaj; "each" kipinde her yeni gemi
        mode = self.conf.get("report_mode", "summary")
        if not rec["sent"] and rec.get("new") and rec.get("dist") is not None:
            near = rec["dist"] <= float(self.conf.get("report_nearby_km", 5.0))
            if near or mode == "each":
                rec["sent"] = True
                self._emit_ship(mmsi, rec, near)

    def _loc(self, rec):
        if rec.get("dist") is None:
            return None
        return f"{float(rec['lat']):.4f}, {float(rec['lon']):.4f} ({rec['dist']:.1f} km {compass_tr(rec['brg'])})"

    def _emit_ship(self, mmsi, rec, near: bool):
        body = [f"MMSI       : <code>{mmsi}</code>", f"Gemi adı   : {rec.get('name') or '—'}",
                f"Çağrı işr. : {rec.get('callsign') or '—'}", f"Tip        : {shiptype_name(rec.get('type'))}"]
        if rec.get("speed") is not None:
            body.append(f"Hız        : {rec['speed']} kn")
        if rec.get("course") is not None:
            try:
                body.append(f"Rota       : {float(rec['course']):.0f}° ({compass_tr(float(rec['course']))})")
            except (TypeError, ValueError):
                pass
        if rec.get("status"):
            body.append(f"Durum      : {rec['status']}")
        if rec.get("dest"):
            body.append(f"Varış      : {rec['dest']}")
        what = "Yakın gemi" if near else "Yeni gemi"
        summary = f"{what} {rec.get('name') or mmsi}" + (f" — {rec['dist']:.1f} km" if rec.get("dist") is not None else "")
        ev = self.make_event(self.NAME, summary=summary, body="\n".join(body), freq_mhz=161.975,
                             lat=rec.get("lat"), lon=rec.get("lon"), location_text=self._loc(rec),
                             priority=(PRIO_IMPORTANT if near else self.priority), dedup_key=f"ship-{mmsi}")
        self.emit(ev)

    def _sart_alarm(self, mmsi, rec):
        prev = self.st.registry_get("ais_sart", mmsi)
        cooldown = float(self.conf.get("sart_realert_min", 30)) * 60
        self.registry_touch("ais_sart", mmsi, {"name": rec.get("name")})
        if prev and time.time() - prev["last_seen"] < cooldown:
            return
        label = SART_PREFIXES[mmsi[:3]]
        body = [f"<b>{label}</b>", f"MMSI: <code>{mmsi}</code>",
                "AIS üzerinden acil durum vericisi yayını alındı. Konum ekteyse doğrulayın; "
                "Sahil Güvenlik 158 / Acil 112."]
        ev = self.make_event(f"ACİL AIS-SART", summary=f"⚠️ {label} — {mmsi}", body="\n".join(body),
                             freq_mhz=161.975, lat=rec.get("lat"), lon=rec.get("lon"),
                             location_text=self._loc(rec), priority=PRIO_EMERGENCY,
                             dedup_key=f"sart-{mmsi}")
        ev.category = Category.ACIL
        self.emit(ev)

    def _finish_slot(self, elapsed: float):
        slot = getattr(self, "_slot", {})
        if not slot or self.conf.get("report_mode", "summary") != "summary":
            return
        new_n = sum(1 for r in slot.values() if r.get("new"))
        with_pos = sorted([(m, r) for m, r in slot.items() if r.get("dist") is not None],
                          key=lambda x: x[1]["dist"])
        lines = []
        for m, r in with_pos[: int(self.conf.get("summary_list_max", 12))]:
            nm = (r.get("name") or m)[:18]
            sp = f"{float(r['speed']):.0f} kn" if r.get("speed") is not None else "—"
            lines.append(f"• {nm:<18} {shiptype_name(r.get('type'))[:10]:<10} {r['dist']:5.1f} km {compass_tr(r['brg'])} {sp}"
                         + ("  🆕" if r.get("new") else ""))
        more = len(slot) - len(lines)
        body = [f"Toplam {len(slot)} gemi ({new_n} yeni), konumlu {len(with_pos)}",
                f"Dinleme süresi: {elapsed:.0f} sn", ""] + lines
        if more > 0:
            body.append(f"… ve {more} gemi daha")
        near_txt = f", en yakın {with_pos[0][1]['dist']:.1f} km" if with_pos else ""
        ev = self.make_event("AIS Özet", summary=f"{len(slot)} gemi görüldü ({new_n} yeni){near_txt}",
                             body="\n".join(body), freq_mhz=161.975, duration_s=elapsed,
                             extra={"ships": len(slot), "new": new_n})
        self.emit(ev)

    def _run_rtl_ais(self, stop_event, secs):
        binary = self.cfg.which("rtl_ais")
        cmd = [binary, "-d", str(self.sdr.device_index), "-n"]
        seen = {"count": 0}

        def on_line(line):
            if line.startswith(("!AIVDM", "!AIVDO")):
                seen["count"] += 1
        self.run_tool_lines(cmd, stop_event, secs, on_line, name="rtl_ais", log_name="rtl_ais")
        if seen["count"]:
            self.emit(self.make_event(self.NAME, summary=f"{seen['count']} AIS cümlesi alındı (ham, çözülmedi)",
                                      body="rtl_ais ham NMEA üretti; tam çözümleme için AIS-catcher kurun.",
                                      freq_mhz=161.975))
