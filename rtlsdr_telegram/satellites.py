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
        self._tle_fail: dict[int, float] = {}
        self._sat_loaded: dict[int, float] = {}
        if HAVE_SKYFIELD:
            self._ts = load.timescale()
            self._topos = wgs84.latlon(self.lat, self.lon, elevation_m=self.alt)

    @property
    def available(self) -> bool:
        return HAVE_SKYFIELD

    # ----------------------------------------------------------------- TLE
    def _tle_path(self, norad: int) -> Path:
        return self.cache_dir / f"{norad}.tle"

    def _tle_sources(self) -> list[str]:
        """Denenecek TLE kaynak URL'leri (sırayla). {norad} yer tutucusu kullanılır."""
        urls = self.sat_cfg.get("tle_urls")
        if isinstance(urls, list) and urls:
            return urls
        single = self.sat_cfg.get("tle_url")
        if single:
            return [single]
        return [
            "https://tle.ivanstanojevic.me/api/tle/{norad}",
            "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle",
        ]

    @staticmethod
    def _parse_tle_response(text: str) -> tuple[str, str] | None:
        """Hem düz TLE metnini hem JSON (line1/line2) biçimini ayrıştırır."""
        text = text.strip()
        if text.startswith("{"):
            try:
                import json
                d = json.loads(text)
                l1, l2 = d.get("line1"), d.get("line2")
                if l1 and l2:
                    return l1.strip(), l2.strip()
            except (ValueError, AttributeError):
                return None
            return None
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
                return lines[i], lines[i + 1]
        return None

    def get_tle(self, norad: int, name: str = "") -> tuple[str, str] | None:
        """NORAD kimliği için (satır1, satır2) TLE döndürür; indirir/önbellekler.

        Birden çok kaynak sırayla denenir. Tüm kaynaklar başarısızsa, bir süre
        (tle_retry_min) yeniden denenmez; varsa eski önbellek yine kullanılır."""
        path = self._tle_path(norad)
        max_age = float(self.sat_cfg.get("tle_max_age_h", 24)) * 3600
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age:
            cached = self._read_tle(path)
            if cached:
                return cached
        # başarısızlık geri çekilmesi: son denemeden bu yana yeterli süre geçmediyse indirme
        retry_s = float(self.sat_cfg.get("tle_retry_min", 30)) * 60
        last_fail = self._tle_fail.get(norad, 0)
        if time.time() - last_fail < retry_s:
            return self._read_tle(path) if path.exists() else None

        import httpx
        for src in self._tle_sources():
            try:
                url = src.format(norad=norad)
            except (KeyError, IndexError):
                url = src
            try:
                r = httpx.get(url, timeout=15, follow_redirects=True,
                              headers={"User-Agent": "rtlsdr-telegram/1.0"})
                r.raise_for_status()
                tle = self._parse_tle_response(r.text)
                if tle:
                    try:
                        path.write_text(f"{name}\n{tle[0]}\n{tle[1]}\n")
                    except OSError:
                        pass
                    self._tle_fail.pop(norad, None)
                    return tle
            except Exception as e:
                self.log.debug("TLE kaynağı başarısız (%s, NORAD %s): %s", url.split('/')[2] if '//' in url else url, norad, e)
                continue
        # tüm kaynaklar başarısız
        self._tle_fail[norad] = time.time()
        self.log.warning("TLE indirilemedi (NORAD %s) — tüm kaynaklar başarısız, %s dk sonra tekrar denenecek",
                         norad, self.sat_cfg.get("tle_retry_min", 30))
        return self._read_tle(path) if path.exists() else None

    @staticmethod
    def _read_tle(path: Path) -> tuple[str, str] | None:
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
                return lines[i], lines[i + 1]
        return None

    def _satellite(self, norad: int, name: str) -> "EarthSatellite | None":
        """EarthSatellite nesnesini döndürür; TLE eskidiyse (tle_max_age_h) yeniler.

        Önceki sürümde nesne süresiz önbelleğe alınıyordu → uzun süre çalışan
        süreçte TLE hiç tazelenmiyor, geçiş tahminleri günler içinde kayıyordu."""
        if not HAVE_SKYFIELD:
            return None
        max_age = float(self.sat_cfg.get("tle_max_age_h", 24)) * 3600
        cached = self._sats.get(norad)
        if cached is not None and (time.time() - self._sat_loaded.get(norad, 0)) < max_age:
            return cached
        tle = self.get_tle(norad, name)
        if not tle:
            return cached  # yenilenemedi; eldeki (eski) nesneyle devam
        sat = EarthSatellite(tle[0], tle[1], name, self._ts)
        self._sats[norad] = sat
        self._sat_loaded[norad] = time.time()
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
        now_dt = datetime.now(timezone.utc)
        for t, ev in zip(times, events):
            dt = t.utc_datetime()
            if ev == 0:
                rise = dt
                max_el = 0.0
            elif ev == 1:
                if rise is None:
                    rise = now_dt  # geçiş zaten sürüyor (başlangıçta pencere içindeyiz)
                culm = dt
                try:
                    alt, _, _ = (sat - self._topos).at(t).altaz()
                    max_el = alt.degrees
                except Exception:
                    max_el = min_elev
            elif ev == 2:
                if rise is None:
                    rise = now_dt  # yalnız batış görüldü: sürmekte olan geçişin sonu
                    if max_el == 0.0:
                        max_el = min_elev
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


    def upcoming(self, sats: list[dict], *, hours: float = 24, limit: int = 8) -> list[Pass]:
        """Birden çok uydu için yaklaşan geçişleri zaman sırasıyla döndürür.

        sats: [{"norad": int, "name": str, "min_elevation": float}, ...]"""
        allp: list[Pass] = []
        now = datetime.now(timezone.utc)
        for sd in sats:
            try:
                ps = self.passes(int(sd["norad"]), str(sd.get("name", sd["norad"])), hours=hours,
                                 min_elev=float(sd.get("min_elevation", 10)))
            except Exception:
                continue
            allp.extend(p for p in ps if p.set > now)
        allp.sort(key=lambda p: p.rise)
        return allp[:limit]
