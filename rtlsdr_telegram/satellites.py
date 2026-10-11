"""Uydu/ISS geçiş hesabı için TLE yönetimi ve skyfield tabanlı tahmin.

TLE verisi Celestrak'tan indirilir ve yerelde önbelleğe alınır (yapılandırılabilir
tazelik). Her uydu için verilen istasyon konumundan görünür geçişler (yükseliş,
doruk, batış ve en yüksek irtifa) hesaplanır. Zamanlayıcı bu pencereleri kullanıp
geçiş anında ilgili frekansa öncelik verir (madde 8).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from skyfield.api import EarthSatellite, load, wgs84
    HAVE_SKYFIELD = True
except ImportError:
    HAVE_SKYFIELD = False


@dataclass
class Pass:
    satellite: str
    rise: datetime      # UTC
    culminate: datetime
    set: datetime
    max_elevation: float

    @property
    def duration_s(self) -> float:
        return (self.set - self.rise).total_seconds()

    def contains(self, t: datetime) -> bool:
        return self.rise <= t <= self.set


class SatellitePredictor:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.sat_cfg = cfg.section("satellites")
        self.cache_dir = cfg.data_dir / "tle"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lat = float(cfg.get("station.lat", 0))
        self.lon = float(cfg.get("station.lon", 0))
        self.alt = float(cfg.get("station.alt_m", 0))
        self._ts = None
        self._topos = None
        self._sats: dict[str, EarthSatellite] = {}
        if HAVE_SKYFIELD:
            self._ts = load.timescale()
            self._topos = wgs84.latlon(self.lat, self.lon, elevation_m=self.alt)

    @property
    def available(self) -> bool:
        return HAVE_SKYFIELD

    # ----------------------------------------------------------------- TLE
    def _tle_path(self, norad: int) -> Path:
        return self.cache_dir / f"{norad}.tle"

    def get_tle(self, norad: int, name: str = "") -> tuple[str, str] | None:
        """NORAD kimliği için (satır1, satır2) TLE döndürür; indirir/önbellekler."""
        path = self._tle_path(norad)
        max_age = float(self.sat_cfg.get("tle_max_age_h", 24)) * 3600
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age:
            return self._read_tle(path)
        url = self.sat_cfg.get("tle_url", "").format(norad=norad)
        if url:
            try:
                import httpx
                r = httpx.get(url, timeout=20, follow_redirects=True)
                r.raise_for_status()
                lines = [ln.strip() for ln in r.text.splitlines() if ln.strip()]
                if len(lines) >= 2:
                    l1, l2 = (lines[-2], lines[-1])
                    path.write_text("\n".join(lines[-3:] if len(lines) >= 3 else lines))
                    return l1, l2
            except Exception as e:
                self.log.warning("TLE indirilemedi (NORAD %s): %s", norad, e)
        if path.exists():
            return self._read_tle(path)
        return None

    @staticmethod
    def _read_tle(path: Path) -> tuple[str, str] | None:
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
                return lines[i], lines[i + 1]
        return None

    def _satellite(self, norad: int, name: str) -> "EarthSatellite | None":
        if not HAVE_SKYFIELD:
            return None
        if norad in self._sats:
            return self._sats[norad]
        tle = self.get_tle(norad, name)
        if not tle:
            return None
        sat = EarthSatellite(tle[0], tle[1], name, self._ts)
        self._sats[norad] = sat
        return sat

    def refresh(self, norad: int, name: str = "") -> None:
        self._sats.pop(norad, None)
        self._satellite(norad, name)

    # --------------------------------------------------------------- geçişler
    def passes(self, norad: int, name: str, *, hours: float = 24, min_elev: float = 15.0) -> list[Pass]:
        sat = self._satellite(norad, name)
        if sat is None:
            return []
        t0 = self._ts.now()
        t1 = self._ts.utc((datetime.now(timezone.utc) + timedelta(hours=hours)))
        try:
            times, events = sat.find_events(self._topos, t0, t1, altitude_degrees=min_elev)
        except Exception as e:
            self.log.warning("geçiş hesabı hatası (%s): %s", name, e)
            return []
        out: list[Pass] = []
        rise = culm = None
        max_el = 0.0
        for t, ev in zip(times, events):
            dt = t.utc_datetime()
            if ev == 0:
                rise = dt
                max_el = 0.0
            elif ev == 1:
                culm = dt
                try:
                    alt, _, _ = (sat - self._topos).at(t).altaz()
                    max_el = alt.degrees
                except Exception:
                    max_el = min_elev
            elif ev == 2 and rise is not None:
                out.append(Pass(name, rise, culm or rise, dt, max_el))
                rise = culm = None
        return out

    def next_pass(self, norad: int, name: str, *, hours: float = 24, min_elev: float = 15.0) -> Pass | None:
        ps = self.passes(norad, name, hours=hours, min_elev=min_elev)
        now = datetime.now(timezone.utc)
        for p in ps:
            if p.set > now:
                return p
        return None
