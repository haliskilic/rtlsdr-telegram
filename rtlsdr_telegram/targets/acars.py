"""Hedef 2 — Uçak veri mesajları: ACARS (VHF ~131 MHz) ve VDL2 (136.7–137 MHz).

Araçlar: acarsdec (ACARS, JSON kipi -o 4) ve dumpvdl2 (VDL2, decoded:json:file:path=-).
Her ikisi de kaynaktan derlenir (Debian deposunda yok). Tek slot içinde dwell
süresi ACARS ve VDL2 arasında paylaştırılır; her alt-faz kendi frekans grubunu
(aynı 2 MHz dilim içinde) dinler.
"""
from __future__ import annotations

import json
import threading
import time

from ..events import Category
from .base import TargetBase


class ACARSTarget(TargetBase):
    NAME = "ACARS/VDL2 Mesaj"
    CATEGORY = Category.HAVACILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 60, "period_s": 600,
        "acars": {"enabled": True, "freqs_mhz": [131.525, 131.725, 131.825], "gain": "auto"},
        "vdl2": {"enabled": True, "freqs_mhz": [136.725, 136.775, 136.875, 136.975], "gain": "auto"},
        "band_label": "131 MHz ACARS / 136.7–137 MHz VDL2",
        "report_all": True,
    }

    def tools_available(self):
        a = self.cfg.which("acarsdec")
        v = self.cfg.which("dumpvdl2")
        if not a and not v:
            return False, "acarsdec ve dumpvdl2 bulunamadı (kaynaktan derlenmeli)"
        return True, ""

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        acars_on = self.conf.get("acars", {}).get("enabled", True) and self.cfg.which("acarsdec")
        vdl2_on = self.conf.get("vdl2", {}).get("enabled", True) and self.cfg.which("dumpvdl2")
        phases = [p for p, on in (("acars", acars_on), ("vdl2", vdl2_on)) if on]
        if not phases:
            self.log.debug("acars/vdl2 araçları yok, atlanıyor")
            return
        share = duration_s / len(phases)
        for phase in phases:
            if stop_event.is_set():
                break
            if phase == "acars":
                self._run_acars(stop_event, share)
            else:
                self._run_vdl2(stop_event, share)

    # ----------------------------------------------------------------- ACARS
    def _run_acars(self, stop_event, secs):
        binary = self.cfg.which("acarsdec")
        conf = self.conf.get("acars", {})
        freqs = [f"{f:.3f}" for f in conf.get("freqs_mhz", [131.725])]
        gain = conf.get("gain", "auto")
        cmd = [binary, "-o", "4", "-r", str(self.sdr.device_index)]
        if gain not in ("auto", "agc", None, -1):
            cmd = [binary, "-o", "4", "-g", str(gain), "-r", str(self.sdr.device_index)]
        cmd += freqs
        self.run_tool_lines(cmd, stop_event, secs, self._on_acars_line, name="acarsdec", log_name="acarsdec")

    def _on_acars_line(self, line: str):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        tail = (d.get("tail") or "").strip().lstrip(".")
        flight = (d.get("flight") or "").strip()
        label = d.get("label", "")
        text = (d.get("text") or "").strip()
        freq = d.get("freq")
        level = d.get("level")
        reg = tail or flight or d.get("msgno") or "?"
        key = f"{tail}|{flight}"
        is_new, _, _ = self.registry_touch("acars_ac", key, {"tail": tail or None, "flight": flight or None})
        if not self.conf.get("report_all", True) and not is_new and not text:
            return
        body = [f"Kuyruk no  : {tail or '—'}", f"Sefer      : {flight or '—'}",
                f"Etiket     : {label or '—'}"]
        if d.get("msgno"):
            body.append(f"Mesaj no   : {d['msgno']}")
        if text:
            body.append(f"\n<b>Mesaj:</b>\n<code>{self._trim(text)}</code>")
        summary = f"ACARS {reg}" + (f" · {label}" if label else "")
        ev = self.make_event(
            "ACARS Mesaj", summary=summary, body="\n".join(body),
            freq_mhz=float(freq) if freq else None, band="131 MHz ACARS",
            signal=(f"{level} dBFS" if level is not None else None), signal_value=level,
            dedup_key=f"acars-{key}")
        self.emit(ev)

    # ------------------------------------------------------------------ VDL2
    def _run_vdl2(self, stop_event, secs):
        binary = self.cfg.which("dumpvdl2")
        conf = self.conf.get("vdl2", {})
        freqs = [str(int(round(f * 1e6))) for f in conf.get("freqs_mhz", [136.975])]
        gain = conf.get("gain", "auto")
        cmd = [binary, "--rtlsdr", str(self.sdr.device_index), "--output", "decoded:json:file:path=-"]
        if gain not in ("auto", "agc", None, -1):
            cmd += ["--gain", str(gain)]
        if self.sdr.ppm:
            cmd += ["--correction", str(self.sdr.ppm)]
        cmd += freqs
        self.run_tool_lines(cmd, stop_event, secs, self._on_vdl2_line, name="dumpvdl2", log_name="dumpvdl2")

    def _on_vdl2_line(self, line: str):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        vdl2 = d.get("vdl2", {})
        freq = vdl2.get("freq")
        freq_mhz = (freq / 1e6) if isinstance(freq, (int, float)) else None
        avlc = vdl2.get("avlc", {})
        src = avlc.get("src", {})
        acars = avlc.get("acars", {})
        icao = src.get("addr")
        reg = (acars.get("reg") or "").strip() if acars else ""
        flight = (acars.get("flight") or "").strip() if acars else ""
        text = (acars.get("msg_text") or "").strip() if acars else ""
        sig = vdl2.get("sig_level")
        key = reg or flight or icao or "?"
        is_new, _, _ = self.registry_touch("vdl2_ac", str(key), {"reg": reg or None, "icao": icao})
        body = [f"ICAO       : <code>{icao or '—'}</code>", f"Kuyruk no  : {reg or '—'}",
                f"Sefer      : {flight or '—'}"]
        if text:
            body.append(f"\n<b>Mesaj:</b>\n<code>{self._trim(text)}</code>")
        summary = f"VDL2 {key}"
        ev = self.make_event(
            "VDL2 Mesaj", summary=summary, body="\n".join(body),
            freq_mhz=freq_mhz, band="136.7–137 MHz VDL2",
            signal=(f"{sig:.1f} dBFS" if isinstance(sig, (int, float)) else None),
            signal_value=sig if isinstance(sig, (int, float)) else None,
            dedup_key=f"vdl2-{key}")
        self.emit(ev)

    @staticmethod
    def _trim(text: str, limit: int = 700) -> str:
        text = text.replace("\r", "")
        return text if len(text) <= limit else text[:limit] + " …"
