"""Configuration loading and validation.

All settings come from a single YAML file (config.yaml). The DEFAULTS dict
below supplies values for missing keys; every target module adds its own
defaults through its `DEFAULTS` class attribute and `Config.target(key)`
merges the two.
"""
from __future__ import annotations

import copy
import os
import platform as _platform
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

# Program-wide defaults. config.example.yaml is the annotated version of this structure.
DEFAULTS: dict[str, Any] = {
    "platform": "auto",            # auto | linux | raspberrypi | windows
    "language": "en",              # UI/Telegram message language: en | tr
    "timezone": "Europe/Istanbul",
    "station": {"name": "RTL-SDR Station", "lat": 41.0082, "lon": 28.9784, "alt_m": 50},
    "paths": {
        "data_dir": "./data",
        "recordings_dir": "./data/recordings",
        "log_dir": "./logs",
        # Circular retention: oldest recordings/events/logs are deleted after this
        # period so the disk never fills up. months/years override retention_days.
        "retention_days": 30,
        "retention_months": 0,
        "retention_years": 0,
        "registry_retention_multiplier": 3,   # device/aircraft/ship memory lives 3x longer
        "tool_log_max_mb": 5,                 # per-tool log (adsb.log ...) rotation size
        "tool_log_backups": 2,
        "min_free_disk_pct": 10,              # below this: stop recording, prune oldest files, warn once/day
        "db_vacuum_days": 30,                 # SQLite VACUUM interval
        "log_level": "INFO",
    },
    "telegram": {
        "token": "",
        "chat_id": 0,
        "thread_id": 0,
        "admins": [],
        "commands_from_any_topic": True,
        "allow_private_admin_commands": True,
        "min_interval_s": 2.0,
        "quiet_priority_from": 4,
        "caption_limit": 1024,
        "startup_message": True,
        "heartbeat_hours": 0,
        "proxy": "",
        "unauthorized_reply": True,
        "poll_timeout_s": 30,
    },
    "sdr": {
        "device_index": 0,
        "serial": "",
        "sample_rate": 2400000,
        "gain": 40,
        "ppm": 0,
        "bias_tee": False,
        "library_path": "",
        "nfft": 4096,
        "usable_bandwidth_ratio": 0.8,
        "settle_ms": 30,
        "read_samples": 262144,
        "center_mask_khz": 5.0,
    },
    "scheduler": {
        "min_slot_s": 10,
        "pass_lead_s": 30,
        "boost_minutes": 30,
        "boost_factor": 10.0,
        "idle_fill": True,
        "no_device_retry_s": 60,
        "grace_s": 8,
        "adhoc_default_s": 120,
    },
    "blacklist": [
        {"name": "FM Radyo", "start_mhz": 87.5, "end_mhz": 108.0},
        {"name": "VHF TV / DAB", "start_mhz": 174.0, "end_mhz": 240.0},
        {"name": "UHF TV (DVB-T2)", "start_mhz": 470.0, "end_mhz": 694.0},
    ],
    "transcription": {
        "engine": "faster_whisper",    # faster_whisper | whisper | api | none
        "model": "base",
        "device": "cpu",
        "compute_type": "int8",
        "language": "auto",            # auto | tr | en
        "timeout_s": 300,
        "vad": True,
        "beam_size": 1,
        "api": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "whisper-1"},
        # Vocabulary hints per category key (aviation, maritime, amateur, emergency ...).
        # Empty = use the built-in bilingual hints from i18n.
        "prompts": {},
    },
    "audio": {
        "format": "ogg",              # ogg | mp3 | wav
        "ffmpeg": "ffmpeg",
        "opus_bitrate": "24k",
        "keep_wav": False,
        "output_rate": 16000,
    },
    "summary": {"enabled": True, "time": "09:00", "attach_csv": True, "top_n": 5},
    "satellites": {
        # Sources tried in order ({norad} placeholder); the first that works is used.
        "tle_urls": [
            "https://tle.ivanstanojevic.me/api/tle/{norad}",
            "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle",
        ],
        "tle_max_age_h": 24,
        "tle_retry_min": 30,     # when all sources fail, retry after this many minutes
        "lookahead_h": 24,
        "refresh_min": 60,
    },
    "targets": {},
}


class ConfigError(Exception):
    """Raised when the configuration file is invalid or missing."""


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dicts (override wins)."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def detect_platform(requested: str = "auto") -> str:
    """Return 'windows' | 'raspberrypi' | 'linux'."""
    req = (requested or "auto").lower()
    if req != "auto":
        return req
    if sys.platform.startswith("win"):
        return "windows"
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore")
        if "Raspberry Pi" in model:
            return "raspberrypi"
    except OSError:
        pass
    if _platform.machine().startswith(("arm", "aarch64")):
        return "raspberrypi"
    return "linux"


class Config:
    """Accessor wrapper around the merged configuration."""

    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path
        self.base_dir = path.parent.resolve() if path else Path.cwd()
        self.platform = detect_platform(data.get("platform", "auto"))
        self._target_defaults: dict[str, dict] = {}

    # ----- generic access -----
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict:
        return self.data.get(name, {}) or {}

    # ----- target configuration -----
    def register_target_defaults(self, key: str, defaults: dict) -> None:
        self._target_defaults[key] = copy.deepcopy(defaults)

    def target(self, key: str) -> dict:
        """Return the target configuration merged with its defaults."""
        base = self._target_defaults.get(key, {})
        user = (self.data.get("targets") or {}).get(key) or {}
        return _deep_merge(base, user)

    def target_keys(self) -> list[str]:
        return list((self.data.get("targets") or {}).keys())

    # ----- paths -----
    def resolve(self, p: str | Path) -> Path:
        path = Path(os.path.expanduser(str(p)))
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.get("paths.data_dir", "./data"))

    @property
    def recordings_dir(self) -> Path:
        return self.resolve(self.get("paths.recordings_dir", "./data/recordings"))

    @property
    def log_dir(self) -> Path:
        return self.resolve(self.get("paths.log_dir", "./logs"))

    def retention_days(self) -> int:
        """Effective retention in days (years/months take precedence over days)."""
        p = self.section("paths")
        years = float(p.get("retention_years", 0) or 0)
        months = float(p.get("retention_months", 0) or 0)
        if years > 0 or months > 0:
            return max(1, int(round(years * 365 + months * 30.44)))
        return max(1, int(p.get("retention_days", 30) or 30))

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.recordings_dir, self.log_dir, self.data_dir / "tmp"):
            d.mkdir(parents=True, exist_ok=True)

    # ----- helpers -----
    def which(self, *names: str) -> str | None:
        """Return the first executable found on PATH among the given names."""
        for n in names:
            if not n:
                continue
            if os.path.sep in n or (os.path.altsep and os.path.altsep in n):
                p = Path(os.path.expanduser(n))
                if p.exists():
                    return str(p)
                continue
            found = shutil.which(n)
            if not found and self.platform == "windows" and not n.lower().endswith(".exe"):
                found = shutil.which(n + ".exe")
            if not found:
                # PATH may be incomplete (systemd / pct exec); also scan standard directories
                for d in ("/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin"):
                    cand = Path(d) / n
                    if cand.exists() and os.access(cand, os.X_OK):
                        found = str(cand)
                        break
            if found:
                return found
        return None

    def blacklist_ranges(self) -> list[tuple[float, float, str]]:
        out = []
        for item in self.data.get("blacklist") or []:
            try:
                out.append((float(item["start_mhz"]), float(item["end_mhz"]), str(item.get("name", ""))))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def is_blacklisted(self, freq_mhz: float) -> bool:
        return any(lo <= freq_mhz <= hi for lo, hi, _ in self.blacklist_ranges())

    def validate(self) -> list[str]:
        """Return critical problems (empty list = fine)."""
        problems = []
        tg = self.section("telegram")
        if not tg.get("token"):
            problems.append("telegram.token is empty")
        if not tg.get("chat_id"):
            problems.append("telegram.chat_id is empty (group id, starts with -100...)")
        st = self.section("station")
        try:
            lat, lon = float(st.get("lat")), float(st.get("lon"))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                problems.append("station.lat/lon out of range")
        except (TypeError, ValueError):
            problems.append("station.lat/lon is not numeric")
        return problems


def load_config(path: str | Path | None = None) -> Config:
    """Read the YAML file and merge it with the defaults."""
    candidates = [path] if path else ["config.yaml", "config.yml", "/etc/rtlsdr-telegram/config.yaml"]
    for cand in candidates:
        if cand and Path(cand).exists():
            p = Path(cand)
            with open(p, "r", encoding="utf-8") as fh:
                user = yaml.safe_load(fh) or {}
            if not isinstance(user, dict):
                raise ConfigError(f"{p}: a top-level mapping is expected")
            # a user-supplied blacklist replaces the default one
            merged = _deep_merge(DEFAULTS, user)
            if "blacklist" in user:
                merged["blacklist"] = user["blacklist"] or []
            return Config(merged, p)
    if path:
        raise ConfigError(f"Configuration file not found: {path}")
    return Config(copy.deepcopy(DEFAULTS), None)
