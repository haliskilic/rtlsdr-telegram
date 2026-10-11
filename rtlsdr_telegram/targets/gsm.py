"""Target 8 — Cellular inventory (GSM 900/1800).

Tool: gr-gsm (grgsm_scanner). ONLY base-station identifiers are decoded:
Cell ID (CID), LAC, MCC/MNC, ARFCN and power. There is NO content decoding —
traffic/voice/SMS is never demodulated or stored; this target passively counts
the cells in the environment ("new/changed cell" alerts).

Legal note: this is a passive inventory of broadcast cell identities. Decoding
or recording cellular content is unlawful and this software does not do it.
"""
from __future__ import annotations

import re
import threading

from ..events import Category
from ..i18n import t
from .base import TargetBase

# grgsm_scanner output line:
# "ARFCN:  975, Freq: 925.2M, CID: 12345, LAC: 6789, MCC: 286, MNC:   1, Pwr: -45"
LINE_RE = re.compile(
    r"ARFCN:\s*(\d+),\s*Freq:\s*([\d.]+)M,\s*CID:\s*(\d+),\s*LAC:\s*(\d+),"
    r"\s*MCC:\s*(\d+),\s*MNC:\s*(\d+),\s*Pwr:\s*(-?\d+)")

# Turkish operators (MCC 286); other networks show MCC/MNC
OPERATORS = {
    ("286", "1"): "Turkcell", ("286", "2"): "Vodafone", ("286", "3"): "Türk Telekom",
    ("286", "4"): "Türk Telekom", ("286", "30"): "Vodafone",
}


class GSMTarget(TargetBase):
    NAME_KEY = "gsm.name"
    BAND_KEY = "gsm.band"
    CATEGORY = Category.HUCRESEL
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 6, "dwell_s": 300, "period_s": 3600,
        # grgsm_scanner prints its results only when a band scan COMPLETES, so the
        # dwell must cover the whole band: GSM900 (174 ARFCNs) takes ~80-90 s at
        # speed 27 on an idle CPU and 2-3x longer while transcription keeps the CPU
        # busy; DCS1800 (374 ARFCNs) needs ~3 min more — add it with a longer dwell_s.
        "bands": ["GSM900"], "gain": 40, "sample_rate": 2000000,
        "speed": 27,                 # grgsm_scanner --speed 0-29 (higher = faster, less sensitive)
        "report_changed": True,
    }

    def tools_available(self):
        ok = self.cfg.which("grgsm_scanner") is not None
        return ok, ("" if ok else "grgsm_scanner not found (gr-gsm not installed)")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        binary = self.cfg.which("grgsm_scanner")
        bands = self.conf.get("bands", ["GSM900", "DCS1800"])
        share = duration_s / max(1, len(bands))
        for band in bands:
            if stop_event.is_set():
                break
            # NOTE: without an explicit --args the osmosdr auto-detection fails silently
            # inside containers (exit code 1, no output); always pass rtl=<index>.
            cmd = [binary, "-b", band, "-g", str(self.conf.get("gain", 40)),
                   "--args", f"rtl={self.sdr.device_index}",
                   f"--speed={int(self.conf.get('speed', 20))}"]
            if self.sdr.ppm:
                cmd += ["-p", str(self.sdr.ppm)]
            self.run_tool_lines(cmd, stop_event, share, self._on_line, name=f"grgsm-{band}",
                                log_name="grgsm")

    def _on_line(self, line: str):
        m = LINE_RE.search(line)
        if not m:
            return
        arfcn, freq, cid, lac, mcc, mnc, pwr = m.groups()
        op = OPERATORS.get((mcc, mnc), f"MCC {mcc}/MNC {mnc}")
        key = f"{mcc}-{mnc}-{lac}-{cid}"
        is_new, _, count = self.registry_touch(
            "gsm_cell", key, {"arfcn": arfcn, "freq": freq, "op": op, "pwr": pwr})
        # changed ARFCN detection
        prev = self.st.registry_get("gsm_cell", key)
        changed = False
        if prev and prev["count"] > 1:
            pdata = prev["data"]
            if pdata.get("arfcn") != arfcn:
                changed = True
        if not is_new and not (changed and self.conf.get("report_changed", True)):
            return
        body = [f"{t('gsm.operator')}: {op}", f"{t('gsm.cid')}: {cid}", f"{t('gsm.lac')}: {lac}",
                f"{t('gsm.mccmnc')}: {mcc}/{mnc}", f"{t('gsm.arfcn')}: {arfcn}", f"{t('gsm.power')}: {pwr} dB"]
        etype = t("evt.gsm_new") if is_new else t("evt.gsm_changed")
        ev = self.make_event(
            etype, summary=t("gsm.summary", what=(t("common.new") if is_new else t("common.changed")), op=op, cid=cid),
            body="\n".join(body), freq_mhz=round(float(freq), 3),
            signal=f"{pwr} dB", signal_value=float(pwr),
            dedup_key=f"gsm-{key}" if is_new else f"gsm-chg-{key}-{arfcn}")
        self.emit(ev)
