"""Target 5 — Wireless sensors (ISM 433.92 and 868 MHz).

Tool: rtl_433 (JSON output). Decodes hundreds of protocols: weather stations,
temperature/humidity sensors, doorbells, tire pressure sensors (TPMS) ...
Both bands (433.92 / 868) are listened to alternately with `-H`. "New device
seen" notifications come from the registry; repeated readings of known devices
are suppressed by default (enable with report_readings).
"""
from __future__ import annotations

import json
import threading

from ..events import Category
from ..i18n import t
from .base import TargetBase, SlotCollector

# rtl_433 field -> (i18n label key, unit)
FIELD_LABELS = {
    "temperature_C": ("ism.r.temperature", "°C"), "temperature_F": ("ism.r.temperature", "°F"),
    "humidity": ("ism.r.humidity", "%"), "pressure_kPa": ("ism.r.pressure", "kPa"), "pressure_hPa": ("ism.r.pressure", "hPa"),
    "wind_avg_km_h": ("ism.r.wind", "km/h"), "wind_speed_km_h": ("ism.r.wind", "km/h"),
    "wind_dir_deg": ("ism.r.wind_dir", "°"), "rain_mm": ("ism.r.rain", "mm"),
    "battery_ok": ("ism.r.battery", ""), "moisture": ("ism.r.moisture", "%"),
    "pressure_PSI": ("ism.r.tire", "PSI"),
}
DOORBELL_HINTS = ("doorbell", "remote", "button")


class ISMTarget(TargetBase):
    NAME_KEY = "ism.name"
    BAND_KEY = "ism.band"
    CATEGORY = Category.ISM
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 60, "period_s": 300,
        "freqs_mhz": [433.92, 868.0], "hop_s": 30, "gain": "auto",
        "report_readings": False,
        "report_new": True,
        "individual_max": 2,      # up to this many new devices get individual messages, the rest one summary
        "summary_list_max": 15,
    }

    def tools_available(self):
        ok = self.cfg.which("rtl_433") is not None
        return ok, ("" if ok else "rtl_433 not found")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        binary = self.cfg.which("rtl_433")
        freqs = self.conf.get("freqs_mhz", [433.92, 868.0])
        gain = self.conf.get("gain", "auto")
        cmd = [binary, "-d", str(self.sdr.device_index), "-F", "json", "-M", "level"]
        for f in freqs:
            cmd += ["-f", f"{int(round(f * 1e6))}"]
        if len(freqs) > 1:
            cmd += ["-H", str(int(self.conf.get("hop_s", 30)))]
        if gain not in ("auto", "agc", None, -1):
            cmd += ["-g", str(gain)]
        if self.sdr.ppm:
            cmd += ["-p", str(self.sdr.ppm)]
        self._collector = SlotCollector(self, t("evt.ism_new"),
                                        individual_max=int(self.conf.get("individual_max", 2)),
                                        list_max=int(self.conf.get("summary_list_max", 15)))
        self._slot_seen: set[str] = set()
        self.run_tool_lines(cmd, stop_event, duration_s, self._on_line, name="rtl_433", log_name="rtl_433")
        self._collector.flush(freq_mhz=None, summary_prefix=t("ism.summary_prefix"),
                              extra_body=t("ism.slot_seen", n=len(self._slot_seen)))

    def _on_line(self, line: str):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        model = d.get("model") or t("common.unknown")
        dev_id = d.get("id", d.get("address", d.get("sensor_id", "")))
        channel = d.get("channel")
        key = f"{model}:{dev_id}" + (f":{channel}" if channel is not None else "")
        rssi = d.get("rssi")
        is_new, first_seen, count = self.registry_touch(
            "ism_device", key, {"model": model, "id": dev_id})

        readings = self._format_readings(d)
        kind = self._classify(model, d)
        self._slot_seen.add(key)
        if not is_new and not self.conf.get("report_readings", False):
            return
        if not is_new and not readings:
            return

        body = [f"{t('ism.model')}: {model}", f"{t('ism.id')}: {dev_id}"]
        if channel is not None:
            body.append(f"{t('ism.channel')}: {channel}")
        if readings:
            body.append("")
            body.extend(readings)
        summary = ((t("ism.new_prefix", kind=kind) + f": {model}") if is_new else f"{model}") + (f" (#{dev_id})" if dev_id != "" else "")
        ev = self.make_event(
            f"ISM {kind}", summary=summary, body="\n".join(body),
            freq_mhz=round(d.get("freq", 0) or 0, 3) or None,
            signal=(f"{rssi:.1f} dBFS" if isinstance(rssi, (int, float)) else None),
            signal_value=rssi if isinstance(rssi, (int, float)) else None,
            dedup_key=f"ism-{key}" if is_new else None)
        if is_new:
            # new devices are flushed at the end of the slot, individually or as one summary (flood control)
            line = f"• {kind}: {model} #{dev_id}" + (f" ({readings[0].split(':')[-1].strip()})" if readings else "")
            self._collector.add(line, ev, sort_key=float(rssi) if isinstance(rssi, (int, float)) else -99)
        else:
            self.emit(ev)

    def _classify(self, model: str, d: dict) -> str:
        m = model.lower()
        if "tpms" in m or "pressure_psi" in {k.lower() for k in d}:
            return t("ism.kind.tpms")
        if any(h in m for h in DOORBELL_HINTS):
            return t("ism.kind.doorbell")
        if any(k in d for k in ("wind_avg_km_h", "wind_speed_km_h", "rain_mm")):
            return t("ism.kind.weather")
        if any(k in d for k in ("temperature_C", "temperature_F", "humidity")):
            return t("ism.kind.temp")
        return t("ism.kind.device")

    @staticmethod
    def _format_readings(d: dict) -> list[str]:
        out = []
        for field, (label_key, unit) in FIELD_LABELS.items():
            if field in d:
                val = d[field]
                label = t(label_key)
                if field == "battery_ok":
                    out.append(f"{label}: {t('ism.battery_ok') if val else t('ism.battery_low')}")
                else:
                    out.append(f"{label}: {val} {unit}".rstrip())
        return out
