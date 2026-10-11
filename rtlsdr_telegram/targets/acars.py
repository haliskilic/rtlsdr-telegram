"""Target 2 — Aircraft data messages: ACARS (VHF ~131 MHz) and VDL2 (136.7–137 MHz).

Tools: acarsdec (ACARS, JSON mode -o 4) and dumpvdl2 (VDL2, decoded:json:file:path=-).
Both are built from source (not in the Debian repositories). Within one slot the
dwell time is shared between ACARS and VDL2; each sub-phase listens to its own
frequency group (within the same 2 MHz window).
"""
from __future__ import annotations

import json
import threading
import time

from ..events import Category
from ..i18n import t
from .base import TargetBase


class ACARSTarget(TargetBase):
    NAME_KEY = "acars.name"
    BAND_KEY = "acars.band"
    CATEGORY = Category.HAVACILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 60, "period_s": 600,
        "acars": {"enabled": True, "freqs_mhz": [131.525, 131.725, 131.825], "gain": "auto"},
        "vdl2": {"enabled": True, "freqs_mhz": [136.725, 136.775, 136.875, 136.975], "gain": "auto"},
        "report_all": True,
        "include_uplinks": True,     # False: aircraft (downlink) messages only (-A)
        "station_id": "RTLTG",
        "max_events_per_slot": 15,  # the rest is collected into one overflow message
    }

    def tools_available(self):
        a = self.cfg.which("acarsdec")
        v = self.cfg.which("dumpvdl2")
        if not a and not v:
            return False, "acarsdec and dumpvdl2 not found (build from source)"
        return True, ""

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        acars_on = self.conf.get("acars", {}).get("enabled", True) and self.cfg.which("acarsdec")
        vdl2_on = self.conf.get("vdl2", {}).get("enabled", True) and self.cfg.which("dumpvdl2")
        phases = [p for p, on in (("acars", acars_on), ("vdl2", vdl2_on)) if on]
        if not phases:
            self.log.debug("acars/vdl2 tools missing, skipping")
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
        cmd = [binary, "-o", "4", "-e"]
        if not self.conf.get("include_uplinks", True):
            cmd.append("-A")
        sid = self.conf.get("station_id")
        if sid:
            cmd += ["-i", str(sid)]
        if not self.sdr.is_auto_gain(gain):
            cmd += ["-g", str(gain)]
        if self.sdr.ppm:
            cmd += ["-p", str(self.sdr.ppm)]
        cmd += ["-r", str(self.sdr.device_index)] + freqs
        self._slot_count = 0
        self._overflow = []
        self.run_tool_lines(cmd, stop_event, secs, self._on_acars_line, name="acarsdec", log_name="acarsdec")
        self._flush_overflow("ACARS")

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
        body = [f"{t('acars.tail')}: {tail or '—'}", f"{t('acars.flight')}: {flight or '—'}",
                f"{t('acars.label')}: {label or '—'}"]
        if d.get("msgno"):
            body.append(f"{t('acars.msgno')}: {d['msgno']}")
        if text:
            body.append(f"\n<b>{t('acars.message')}:</b>\n<code>{self._trim(text)}</code>")
        summary = f"ACARS {reg}" + (f" · {label}" if label else "")
        ev = self.make_event(
            t("evt.acars"), summary=summary, body="\n".join(body),
            freq_mhz=float(freq) if freq else None, band=t("acars.band_acars"),
            signal=(f"{level} dBFS" if level is not None else None), signal_value=level,
            dedup_key=f"acars-{key}")
        self._emit_capped(ev, summary)

    # ------------------------------------------------------------------ VDL2
    def _run_vdl2(self, stop_event, secs):
        binary = self.cfg.which("dumpvdl2")
        conf = self.conf.get("vdl2", {})
        freqs = [str(int(round(f * 1e6))) for f in conf.get("freqs_mhz", [136.975])]
        gain = conf.get("gain", "auto")
        cmd = [binary, "--rtlsdr", str(self.sdr.device_index), "--output", "decoded:json:file:path=-"]
        if not self.sdr.is_auto_gain(gain):
            cmd += ["--gain", str(gain)]
        if self.sdr.ppm:
            cmd += ["--correction", str(self.sdr.ppm)]
        cmd += freqs
        self._slot_count = 0
        self._overflow = []
        self.run_tool_lines(cmd, stop_event, secs, self._on_vdl2_line, name="dumpvdl2", log_name="dumpvdl2")
        self._flush_overflow("VDL2")

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
        body = [f"ICAO: <code>{icao or '—'}</code>", f"{t('acars.tail')}: {reg or '—'}",
                f"{t('acars.flight')}: {flight or '—'}"]
        if text:
            body.append(f"\n<b>{t('acars.message')}:</b>\n<code>{self._trim(text)}</code>")
        summary = f"VDL2 {key}"
        ev = self.make_event(
            t("evt.vdl2"), summary=summary, body="\n".join(body),
            freq_mhz=freq_mhz, band=t("acars.band_vdl2"),
            signal=(f"{sig:.1f} dBFS" if isinstance(sig, (int, float)) else None),
            signal_value=sig if isinstance(sig, (int, float)) else None,
            dedup_key=f"vdl2-{key}")
        self._emit_capped(ev, summary)

    # ---------------------------------------------------- per-slot cap
    _slot_count = 0
    _overflow: list = []

    def _emit_capped(self, ev, line: str):
        cap = int(self.conf.get("max_events_per_slot", 15))
        if self._slot_count < cap:
            self._slot_count += 1
            self.emit(ev)
        else:
            self._overflow.append(line)

    def _flush_overflow(self, label: str):
        if not self._overflow:
            return
        n = len(self._overflow)
        body = "\n".join(f"• {l}" for l in self._overflow[:30])
        if n > 30:
            body += "\n" + t("acars.more", n=n - 30)
        ev = self.make_event(t("evt.acars_overflow", label=label), summary=t("acars.overflow_summary", n=n, label=label),
                             body=body, priority=self.priority + 1)
        self.emit(ev)
        self._overflow = []

    @staticmethod
    def _trim(text: str, limit: int = 700) -> str:
        text = text.replace("\r", "")
        return text if len(text) <= limit else text[:limit] + " …"
