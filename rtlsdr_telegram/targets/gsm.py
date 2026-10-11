"""Hedef 8 — Hücresel envanter (GSM 900/1800).

Araç: gr-gsm (grgsm_scanner). SADECE baz istasyonu kimlikleri çözülür:
Cell ID (CID), LAC, MCC/MNC, ARFCN, güç. İÇERİK ÇÖZME YOKTUR — trafik/konuşma/SMS
hiçbir şekilde demodüle veya kaydedilmez; bu hedef yalnızca ortamdaki hücreleri
pasif olarak sayar ("yeni/değişen hücre" uyarısı).

Yasal not: Bu, hücre yayın kimliklerinin pasif envanteridir. Hücresel içeriğin
çözülmesi/kaydı yasalara aykırıdır ve bu yazılım bunu yapmaz.
"""
from __future__ import annotations

import re
import threading

from ..events import Category
from .base import TargetBase

# grgsm_scanner çıktı satırı:
# "ARFCN:  975, Freq: 925.2M, CID: 12345, LAC: 6789, MCC: 286, MNC:   1, Pwr: -45"
LINE_RE = re.compile(
    r"ARFCN:\s*(\d+),\s*Freq:\s*([\d.]+)M,\s*CID:\s*(\d+),\s*LAC:\s*(\d+),"
    r"\s*MCC:\s*(\d+),\s*MNC:\s*(\d+),\s*Pwr:\s*(-?\d+)")

# Türkiye operatörleri (MCC 286)
OPERATORS = {
    ("286", "1"): "Turkcell", ("286", "2"): "Vodafone", ("286", "3"): "Türk Telekom",
    ("286", "4"): "Türk Telekom", ("286", "30"): "Vodafone",
}


class GSMTarget(TargetBase):
    NAME = "GSM Hücre"
    CATEGORY = Category.HUCRESEL
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 6, "dwell_s": 90, "period_s": 3600,
        "bands": ["GSM900", "DCS1800"], "gain": 40, "sample_rate": 2000000,
        "band_label": "GSM 900 / 1800 (yalnız kimlik)", "report_changed": True,
    }

    def tools_available(self):
        ok = self.cfg.which("grgsm_scanner") is not None
        return ok, ("" if ok else "grgsm_scanner yok (gr-gsm kurulu değil)")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        binary = self.cfg.which("grgsm_scanner")
        bands = self.conf.get("bands", ["GSM900", "DCS1800"])
        share = duration_s / max(1, len(bands))
        for band in bands:
            if stop_event.is_set():
                break
            cmd = [binary, "-b", band, "-g", str(self.conf.get("gain", 40))]
            if self.sdr.ppm:
                cmd += ["-p", str(self.sdr.ppm)]
            self._found = []
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
        # Değişen güç/ARFCN tespiti
        prev = self.st.registry_get("gsm_cell", key)
        changed = False
        if prev and prev["count"] > 1:
            pdata = prev["data"]
            if pdata.get("arfcn") != arfcn:
                changed = True
        if not is_new and not (changed and self.conf.get("report_changed", True)):
            return
        body = [f"Operatör   : {op}", f"Cell ID    : {cid}", f"LAC        : {lac}",
                f"MCC/MNC    : {mcc}/{mnc}", f"ARFCN      : {arfcn}", f"Güç        : {pwr} dB"]
        etype = "Yeni GSM Hücre" if is_new else "GSM Hücre Değişti"
        ev = self.make_event(
            etype, summary=f"{'Yeni' if is_new else 'Değişen'} hücre — {op}, CID {cid}",
            body="\n".join(body), freq_mhz=round(float(freq), 3),
            signal=f"{pwr} dB", signal_value=float(pwr),
            dedup_key=f"gsm-{key}" if is_new else f"gsm-chg-{key}-{arfcn}")
        self.emit(ev)
