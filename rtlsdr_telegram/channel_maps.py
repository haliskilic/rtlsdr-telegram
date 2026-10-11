"""Known channel plans: marine VHF, PMR446, CB, airband and amateur landmarks.

Used only for frequency -> human-readable channel names, which enrich message
headers ("156.800 MHz · Channel 16 (Distress/Calling)" instead of a bare number).
Names are localized through i18n and rebuilt when the language changes.
"""
from __future__ import annotations

from .i18n import t, get_language

_TOL = 0.0026  # MHz (2.6 kHz) matching tolerance

# --- Marine VHF (ITU Appendix 18) ---
_MARINE_DUPLEX_LOW = {1, 2, 3, 4, 5, 7, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28}
_MARINE_DUPLEX_HIGH = set(range(60, 67)) | set(range(78, 87))
_MARINE_NOTE_KEYS = {16: "ch.m16", 70: "ch.m70", 13: "ch.m13", 6: "ch.m6", 12: "ch.m12", 14: "ch.m14",
                     9: "ch.m9", 10: "ch.m10", 11: "ch.m11", 67: "ch.m67", 72: "ch.m72", 73: "ch.m73",
                     77: "ch.m77", 8: "ch.m8", 15: "ch.m15", 17: "ch.m17"}

_CB_FREQS = [26.965, 26.975, 26.985, 27.005, 27.015, 27.025, 27.035, 27.055, 27.065, 27.075,
             27.085, 27.105, 27.115, 27.125, 27.135, 27.155, 27.165, 27.175, 27.185, 27.205,
             27.215, 27.225, 27.255, 27.235, 27.245, 27.265, 27.275, 27.285, 27.295, 27.305,
             27.315, 27.325, 27.335, 27.345, 27.355, 27.365, 27.375, 27.385, 27.395, 27.405]
_CB_NOTE_KEYS = {9: "ch.cb9", 19: "ch.cb19"}
_AIR_KEYS = {121.500: "ch.air1215", 123.450: "ch.air12345", 243.000: "ch.air243"}
_AMATEUR_KEYS = {145.500: "ch.am1455", 144.800: "ch.am1448", 145.800: "ch.am1458",
                 145.825: "ch.am145825", 433.500: "ch.am4335", 144.300: "ch.am1443"}

_cache: dict[str, dict[str, dict[float, str]]] = {}


def _marine_table() -> dict[float, str]:
    ch_word = t("ch.channel")
    coast = t("ch.coast")
    table: dict[float, str] = {}
    for ch in range(1, 29):
        ship = round(156.050 + (ch - 1) * 0.05, 4)
        note = t(_MARINE_NOTE_KEYS[ch]) if ch in _MARINE_NOTE_KEYS else None
        label = f"{ch_word} {ch}" + (f" ({note})" if note else "")
        table[ship] = label
        if ch in _MARINE_DUPLEX_LOW:
            table[round(ship + 4.6, 4)] = f"{label} {coast}"
    for ch in range(60, 89):
        ship = round(156.025 + (ch - 60) * 0.05, 4)
        note = t(_MARINE_NOTE_KEYS[ch]) if ch in _MARINE_NOTE_KEYS else None
        label = f"{ch_word} {ch}" + (f" ({note})" if note else "")
        table[ship] = label
        if ch in _MARINE_DUPLEX_HIGH:
            table[round(ship + 4.6, 4)] = f"{label} {coast}"
    table[161.975] = t("ch.ais1")
    table[162.025] = t("ch.ais2")
    return table


def _tables() -> dict[str, dict[float, str]]:
    lang = get_language()
    if lang in _cache:
        return _cache[lang]
    cb = {f: f"{t('ch.cb')} {i + 1}" + (f" ({t(_CB_NOTE_KEYS[i + 1])})" if (i + 1) in _CB_NOTE_KEYS else "")
          for i, f in enumerate(_CB_FREQS)}
    tables = {
        "marine": _marine_table(),
        "pmr": {round(446.00625 + (n - 1) * 0.0125, 5): f"{t('ch.pmr')} {n}" for n in range(1, 17)},
        "cb": cb,
        "air": {f: t(k) for f, k in _AIR_KEYS.items()},
        "amateur": {f: t(k) for f, k in _AMATEUR_KEYS.items()},
    }
    _cache[lang] = tables
    return tables


def _lookup(table: dict[float, str], freq_mhz: float) -> str | None:
    best, best_d = None, _TOL
    for f, name in table.items():
        d = abs(f - freq_mhz)
        if d <= best_d:
            best, best_d = name, d
    return best


def channel_name(freq_mhz: float, hint: str | None = None) -> str | None:
    """Known channel name for a frequency in the active language (or None)."""
    tables = _tables()
    if hint and hint in tables:
        return _lookup(tables[hint], freq_mhz)
    for table in tables.values():
        name = _lookup(table, freq_mhz)
        if name:
            return name
    return None


def describe(freq_mhz: float, hint: str | None = None) -> str:
    """'156.800 MHz · Channel 16 (Distress/Calling)' style text."""
    name = channel_name(freq_mhz, hint)
    base = f"{freq_mhz:.4f} MHz".rstrip("0").rstrip(".")
    if "." not in base.split(" ")[0]:
        base = f"{freq_mhz:.3f} MHz"
    return f"{base} · {name}" if name else base


# Module-level aliases kept for tests/back-compat (English tables at import time).
MARINE = _tables()["marine"]
PMR446 = _tables()["pmr"]
CB = _tables()["cb"]
