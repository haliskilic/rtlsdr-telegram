"""Target 3 — Vessel tracking (AIS, 161.975 and 162.025 MHz).

Tool: AIS-catcher (full JSON output, -o 5). Both AIS channels are received at
once. Vessel name, MMSI, type, position, course/speed are decoded; the vessel
record is merged in the registry (static messages fill in the name later).

Flood control: busy waters (e.g. the Sea of Marmara) show hundreds of vessels.
Default: one summary per slot (nearest vessels list); only NEW and NEARBY
vessels get an individual message. AIS SART/MOB/EPIRB-AIS (MMSI 970/972/974)
raise an EMERGENCY alarm.
"""
from __future__ import annotations

import json
import threading
import time

from ..events import Category, PRIO_EMERGENCY, PRIO_IMPORTANT
from ..geo import haversine_km, bearing_deg, compass
from ..i18n import t
from .base import TargetBase

SHIPTYPE_KEYS = {
    30: "st.fishing", 31: "st.tug", 32: "st.tug", 33: "st.dredging", 34: "st.diving",
    35: "st.military", 36: "st.sailing", 37: "st.pleasure", 50: "st.pilot", 51: "st.sar",
    52: "st.tug", 53: "st.tender", 54: "st.antipollution", 55: "st.law",
    58: "st.medical", 60: "st.passenger", 70: "st.cargo", 80: "st.tanker", 90: "st.other",
}
SART_PREFIXES = {"970": "sart.970", "972": "sart.972", "974": "sart.974"}


def shiptype_name(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "—"
    key = SHIPTYPE_KEYS.get(c) or SHIPTYPE_KEYS.get((c // 10) * 10)
    return t(key) if key else t("st.type_n", n=c)


class AISTarget(TargetBase):
    NAME_KEY = "ais.name"
    BAND_KEY = "ais.band"
    CATEGORY = Category.DENIZCILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 90, "period_s": 300,
        "gain": "auto",
        "report_mode": "summary",       # summary | each
        "report_nearby_km": 5.0,        # new vessels within this distance get their own message
        "summary_list_max": 12,
        "sart_realert_min": 30,
    }

    def tools_available(self):
        if self.cfg.which("AIS-catcher"):
            return True, ""
        if self.cfg.which("rtl_ais"):
            return True, "(rtl_ais only — limited)"
        return False, "AIS-catcher / rtl_ais not found"

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

    # -------------------------------------------------------------- parsing
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
            # enrich the registry when the name arrives later
            if rec.get("name"):
                self.registry_touch("ship", mmsi, {"name": rec.get("name"), "type": rec.get("type")})
        # distress transmitters
        if mmsi[:3] in SART_PREFIXES:
            self._sart_alarm(mmsi, rec)
            return
        # new + nearby vessel -> individual message; every new vessel in "each" mode
        mode = self.conf.get("report_mode", "summary")
        if not rec["sent"] and rec.get("new") and rec.get("dist") is not None:
            near = rec["dist"] <= float(self.conf.get("report_nearby_km", 5.0))
            if near or mode == "each":
                rec["sent"] = True
                self._emit_ship(mmsi, rec, near)

    def _loc(self, rec):
        if rec.get("dist") is None:
            return None
        return f"{float(rec['lat']):.4f}, {float(rec['lon']):.4f} ({rec['dist']:.1f} km {compass(rec['brg'])})"

    def _emit_ship(self, mmsi, rec, near: bool):
        body = [f"{t('ais.mmsi')}: <code>{mmsi}</code>", f"{t('ais.vessel')}: {rec.get('name') or '—'}",
                f"{t('ais.callsign')}: {rec.get('callsign') or '—'}", f"{t('ais.type')}: {shiptype_name(rec.get('type'))}"]
        if rec.get("speed") is not None:
            body.append(f"{t('ais.speed')}: {rec['speed']} kn")
        if rec.get("course") is not None:
            try:
                body.append(f"{t('ais.course')}: {float(rec['course']):.0f}° ({compass(float(rec['course']))})")
            except (TypeError, ValueError):
                pass
        if rec.get("status"):
            body.append(f"{t('ais.status')}: {rec['status']}")
        if rec.get("dest"):
            body.append(f"{t('ais.dest')}: {rec['dest']}")
        what = t("ais.nearby") if near else t("ais.new")
        summary = f"{what} {rec.get('name') or mmsi}" + (f" — {rec['dist']:.1f} km" if rec.get("dist") is not None else "")
        ev = self.make_event(self.display_name(), summary=summary, body="\n".join(body), freq_mhz=161.975,
                             lat=rec.get("lat"), lon=rec.get("lon"), location_text=self._loc(rec),
                             priority=(PRIO_IMPORTANT if near else self.priority), dedup_key=f"ship-{mmsi}")
        self.emit(ev)

    def _sart_alarm(self, mmsi, rec):
        prev = self.st.registry_get("ais_sart", mmsi)
        cooldown = float(self.conf.get("sart_realert_min", 30)) * 60
        self.registry_touch("ais_sart", mmsi, {"name": rec.get("name")})
        if prev and time.time() - prev["last_seen"] < cooldown:
            return
        label = t(SART_PREFIXES[mmsi[:3]])
        body = [f"<b>{label}</b>", f"MMSI: <code>{mmsi}</code>", t("ais.sart_body")]
        ev = self.make_event(t("evt.ais_sart"), summary=f"⚠️ {label} — {mmsi}", body="\n".join(body),
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
            lines.append(f"• {nm:<18} {shiptype_name(r.get('type'))[:10]:<10} {r['dist']:5.1f} km {compass(r['brg'])} {sp}"
                         + ("  🆕" if r.get("new") else ""))
        more = len(slot) - len(lines)
        body = [t("ais.total", n=len(slot), new=new_n, pos=len(with_pos)),
                f"{t('common.listen_time')}: {elapsed:.0f} {t('unit.s')}", ""] + lines
        if more > 0:
            body.append(t("ais.more", n=more))
        near_txt = t("adsb.nearest", d=f"{with_pos[0][1]['dist']:.1f}") if with_pos else ""
        ev = self.make_event(t("evt.ais_summary"), summary=t("ais.summary_line", n=len(slot), new=new_n) + near_txt,
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
            self.emit(self.make_event(self.display_name(), summary=t("ais.raw_summary", n=seen["count"]),
                                      body=t("ais.raw_body"), freq_mhz=161.975))
