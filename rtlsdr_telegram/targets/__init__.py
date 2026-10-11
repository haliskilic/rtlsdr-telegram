"""İzlenecek 16 hedef + spektrum gözcüsü. Her hedef ayrı bir modül/sınıftır.

`ALL_TARGETS` kayıt sırası, `build_targets(ctx)` ise yapılandırmaya göre etkin
hedef nesnelerini üretir.
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

# config.targets anahtarı -> sınıf
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

# Varsayılan tarama/öncelik sırası (config'de yoksa bu sırayla kaydedilir)
DEFAULT_ORDER = list(TARGET_CLASSES.keys())


def build_targets(ctx: "TargetContext") -> list[TargetBase]:
    """Yapılandırmadaki (veya varsayılan) sıraya göre etkin hedefleri üretir."""
    targets = []
    for key, cls in TARGET_CLASSES.items():
        cls.register_defaults(ctx.cfg, key)
    keys = ctx.cfg.target_keys() or DEFAULT_ORDER
    # bilinen tüm anahtarları kapsa (config'de eksik olsa da varsayılanla)
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
