"""Bilinen kanal planları: Deniz VHF, PMR446, CB, hava bandı ve amatör işaret frekansları.

Sadece frekans → okunur kanal adı dönüşümü için kullanılır; mesaj başlıklarını
zenginleştirir ("156.800 MHz" yerine "Kanal 16 (Acil/Çağrı)").
"""
from __future__ import annotations

_TOL = 0.0026  # MHz (2.6 kHz) eşleştirme toleransı

# --- Deniz VHF (ITU Appendix 18) ---
_MARINE_SIMPLEX_LOW = {6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17}
_MARINE_DUPLEX_LOW = {1, 2, 3, 4, 5, 7, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28}
_MARINE_SIMPLEX_HIGH = set(range(67, 78)) | {87, 88}
_MARINE_DUPLEX_HIGH = set(range(60, 67)) | set(range(78, 87))
_MARINE_NOTES = {
    16: "Acil/Çağrı", 70: "DSC (dijital)", 13: "Köprü-köprü emniyet", 6: "Gemi-gemi / SAR",
    12: "Liman/VTS", 14: "Liman/VTS", 9: "Çağrı (yedek)", 10: "Liman operasyon",
    11: "Liman operasyon", 67: "SAR / Küçük tekne", 72: "Gemi-gemi", 73: "Gemi-gemi",
    77: "Gemi-gemi", 8: "Gemi-gemi", 15: "Gemi içi", 17: "Gemi içi",
}


def _marine_table() -> dict[float, str]:
    table: dict[float, str] = {}
    for ch in range(1, 29):
        ship = round(156.050 + (ch - 1) * 0.05, 4)
        note = _MARINE_NOTES.get(ch)
        label = f"Kanal {ch}" + (f" ({note})" if note else "")
        table[ship] = label
        if ch in _MARINE_DUPLEX_LOW:
            table[round(ship + 4.6, 4)] = label + " [sahil]"
    for ch in range(60, 89):
        ship = round(156.025 + (ch - 60) * 0.05, 4)
        note = _MARINE_NOTES.get(ch)
        label = f"Kanal {ch}" + (f" ({note})" if note else "")
        table[ship] = label
        if ch in _MARINE_DUPLEX_HIGH:
            table[round(ship + 4.6, 4)] = label + " [sahil]"
    table[161.975] = "AIS 1 (87B)"
    table[162.025] = "AIS 2 (88B)"
    table[156.525] = "Kanal 70 (DSC (dijital))"
    return table


MARINE = _marine_table()

# --- PMR446 (16 analog kanal) ---
PMR446 = {round(446.00625 + (n - 1) * 0.0125, 5): f"PMR Kanal {n}" for n in range(1, 17)}

# --- CB (CEPT 40 kanal) ---
_CB_FREQS = [26.965, 26.975, 26.985, 27.005, 27.015, 27.025, 27.035, 27.055, 27.065, 27.075,
             27.085, 27.105, 27.115, 27.125, 27.135, 27.155, 27.165, 27.175, 27.185, 27.205,
             27.215, 27.225, 27.255, 27.235, 27.245, 27.265, 27.275, 27.285, 27.295, 27.305,
             27.315, 27.325, 27.335, 27.345, 27.355, 27.365, 27.375, 27.385, 27.395, 27.405]
_CB_NOTES = {9: "Acil", 19: "Karayolu"}
CB = {f: f"CB Kanal {i + 1}" + (f" ({_CB_NOTES[i + 1]})" if (i + 1) in _CB_NOTES else "")
      for i, f in enumerate(_CB_FREQS)}

# --- Hava bandı ve amatör işaret frekansları ---
AIR = {121.500: "Acil (Guard)", 123.450: "Hava-hava", 243.000: "Askeri acil"}
AMATEUR = {145.500: "2m çağrı (simpleks)", 144.800: "APRS", 145.800: "ISS ses/SSTV",
           145.825: "ISS paket", 433.500: "70cm çağrı (simpleks)", 144.300: "2m SSB çağrı"}

_ALL_TABLES = {"marine": MARINE, "pmr": PMR446, "cb": CB, "air": AIR, "amateur": AMATEUR}


def _lookup(table: dict[float, str], freq_mhz: float) -> str | None:
    best, best_d = None, _TOL
    for f, name in table.items():
        d = abs(f - freq_mhz)
        if d <= best_d:
            best, best_d = name, d
    return best


def channel_name(freq_mhz: float, hint: str | None = None) -> str | None:
    """Frekans için bilinen kanal adını döndürür (yoksa None)."""
    if hint and hint in _ALL_TABLES:
        return _lookup(_ALL_TABLES[hint], freq_mhz)
    for table in _ALL_TABLES.values():
        name = _lookup(table, freq_mhz)
        if name:
            return name
    return None


def describe(freq_mhz: float, hint: str | None = None) -> str:
    """'156.800 MHz · Kanal 16 (Acil/Çağrı)' biçiminde metin."""
    name = channel_name(freq_mhz, hint)
    base = f"{freq_mhz:.4f} MHz".rstrip("0").rstrip(".")
    if "." not in base.split(" ")[0]:
        base = f"{freq_mhz:.3f} MHz"
    return f"{base} · {name}" if name else base
