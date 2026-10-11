"""Hedef 5 — Kablosuz sensörler (ISM 433.92 ve 868 MHz).

Araç: rtl_433 (JSON çıktısı). Hava istasyonu, sıcaklık/nem sensörü, kapı zili,
lastik basıncı (TPMS) vb. yüzlerce protokolü çözer. İki bandı (433.92 / 868)
`-H` ile dönüşümlü dinler. "Yeni cihaz görüldü" bildirimi kayıt defteriyle
yapılır; aynı cihazın tekrar okumaları varsayılan olarak bastırılır
(report_readings ile açılabilir).
"""
from __future__ import annotations

import json
import threading

from ..events import Category
from .base import TargetBase, SlotCollector

# rtl_433 alan adı -> okunur etiket
FIELD_LABELS = {
    "temperature_C": ("Sıcaklık", "°C"), "temperature_F": ("Sıcaklık", "°F"),
    "humidity": ("Nem", "%"), "pressure_kPa": ("Basınç", "kPa"), "pressure_hPa": ("Basınç", "hPa"),
    "wind_avg_km_h": ("Rüzgar", "km/s"), "wind_speed_km_h": ("Rüzgar", "km/s"),
    "wind_dir_deg": ("Rüzgar yönü", "°"), "rain_mm": ("Yağış", "mm"),
    "battery_ok": ("Pil", ""), "moisture": ("Nem/toprak", "%"),
    "pressure_PSI": ("Lastik", "PSI"), "pressure_kPa_tpms": ("Lastik", "kPa"),
}

# Protokol/model -> kategori ipucu
DOORBELL_HINTS = ("doorbell", "remote", "button")
TPMS_HINTS = ("TPMS", "Tpms", "tpms")


class ISMTarget(TargetBase):
    NAME = "ISM Sensör"
    CATEGORY = Category.ISM
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 60, "period_s": 300,
        "freqs_mhz": [433.92, 868.0], "hop_s": 30, "gain": "auto",
        "band_label": "433.92 / 868 MHz ISM", "report_readings": False,
        "report_new": True,
        "individual_max": 2,      # bu sayıya kadar yeni cihaz ayrı mesaj, fazlası tek özet
        "summary_list_max": 15,
    }

    def tools_available(self):
        ok = self.cfg.which("rtl_433") is not None
        return ok, ("" if ok else "rtl_433 yok")

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
        self._collector = SlotCollector(self, "ISM Yeni Cihazlar",
                                        individual_max=int(self.conf.get("individual_max", 2)),
                                        list_max=int(self.conf.get("summary_list_max", 15)))
        self._slot_seen: set[str] = set()
        self.run_tool_lines(cmd, stop_event, duration_s, self._on_line, name="rtl_433", log_name="rtl_433")
        self._collector.flush(freq_mhz=None, summary_prefix="Yeni cihaz: ",
                              extra_body=f"Bu slotta {len(self._slot_seen)} farklı cihaz duyuldu.")

    def _on_line(self, line: str):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        model = d.get("model") or "Bilinmeyen"
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

        body = [f"Model      : {model}", f"Kimlik     : {dev_id}"]
        if channel is not None:
            body.append(f"Kanal      : {channel}")
        if readings:
            body.append("")
            body.extend(readings)
        summary = (f"Yeni {kind}: {model}" if is_new else f"{model}") + (f" (#{dev_id})" if dev_id != "" else "")
        ev = self.make_event(
            f"ISM {kind}", summary=summary, body="\n".join(body),
            freq_mhz=round(d.get("freq", 0) or 0, 3) or None,
            signal=(f"{rssi:.1f} dBFS" if isinstance(rssi, (int, float)) else None),
            signal_value=rssi if isinstance(rssi, (int, float)) else None,
            dedup_key=f"ism-{key}" if is_new else None)
        if is_new:
            # yeni cihazlar slot sonunda toplu/ayrı gönderilir (sel koruması)
            line = f"• {kind}: {model} #{dev_id}" + (f" ({readings[0].split(':')[-1].strip()})" if readings else "")
            self._collector.add(line, ev, sort_key=float(rssi) if isinstance(rssi, (int, float)) else -99)
        else:
            self.emit(ev)

    def _classify(self, model: str, d: dict) -> str:
        m = model.lower()
        if "tpms" in m or "pressure_psi" in {k.lower() for k in d}:
            return "Lastik (TPMS)"
        if any(h in m for h in DOORBELL_HINTS):
            return "Kapı zili/Kumanda"
        if any(k in d for k in ("wind_avg_km_h", "wind_speed_km_h", "rain_mm")):
            return "Hava istasyonu"
        if any(k in d for k in ("temperature_C", "temperature_F", "humidity")):
            return "Sıcaklık/Nem sensörü"
        return "Cihaz"

    @staticmethod
    def _format_readings(d: dict) -> list[str]:
        out = []
        for field, (label, unit) in FIELD_LABELS.items():
            if field in d:
                val = d[field]
                if field == "battery_ok":
                    out.append(f"{label}      : {'iyi' if val else 'ZAYIF ⚠️'}")
                else:
                    out.append(f"{label}      : {val} {unit}".rstrip())
        return out
