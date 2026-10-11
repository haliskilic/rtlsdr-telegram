"""The 16 monitoring targets. Each target is its own module/class.

`DEFAULT_ORDER` is the registration order; `build_targets(ctx)` instantiates
the targets according to the configuration.
"""
from __future__ import annotations

from .base import TargetBase, TargetContext
from .adsb import ADSBTarget
from .acars import ACARSTarget
from .ais import AISTarget
from .radiosonde import RadiosondeTarget
from .ism import ISMTarget
from .aprs import APRSTarget
from .emergency import EmergencyTarget
from .gsm import GSMTarget
from .voice import (AmateurVoiceTarget, AirbandTarget, MarineVoiceTarget, CBPMRTarget)
from .meteor import MeteorTarget
from .iss import ISSTarget
from .inmarsat import InmarsatTarget
from .spectrum import SpectrumTarget

# config.targets key -> class
TARGET_CLASSES = {
    "adsb": ADSBTarget,
    "acars": ACARSTarget,
    "ais": AISTarget,
    "radiosonde": RadiosondeTarget,
    "ism": ISMTarget,
    "aprs": APRSTarget,
    "emergency": EmergencyTarget,
    "gsm": GSMTarget,
    "amateur_voice": AmateurVoiceTarget,
    "airband": AirbandTarget,
    "marine_voice": MarineVoiceTarget,
    "cb_pmr": CBPMRTarget,
    "meteor": MeteorTarget,
    "iss": ISSTarget,
    "inmarsat": InmarsatTarget,
    "spectrum": SpectrumTarget,
}

# default registration order (used when config.targets does not list a key)
DEFAULT_ORDER = list(TARGET_CLASSES.keys())


def build_targets(ctx: "TargetContext") -> list[TargetBase]:
    """Instantiate targets in configuration (or default) order."""
    targets = []
    for key, cls in TARGET_CLASSES.items():
        cls.register_defaults(ctx.cfg, key)
    keys = ctx.cfg.target_keys() or DEFAULT_ORDER
    # cover every known key (defaults apply when missing from config)
    seen = set()
    ordered = [k for k in keys if k in TARGET_CLASSES] + [k for k in DEFAULT_ORDER if k not in keys]
    for key in ordered:
        if key in seen:
            continue
        seen.add(key)
        cls = TARGET_CLASSES[key]
        inst = cls(key, ctx)
        targets.append(inst)
    return targets


__all__ = ["build_targets", "TARGET_CLASSES", "DEFAULT_ORDER", "TargetBase", "TargetContext"]
