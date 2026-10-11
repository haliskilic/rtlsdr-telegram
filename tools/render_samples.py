#!/usr/bin/env python3
"""Render representative Telegram messages as plain text (for the README).

Usage: python3 tools/render_samples.py [en|tr]
"""
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from rtlsdr_telegram.i18n import set_language, t  # noqa: E402
from rtlsdr_telegram.events import Event, Category, Attachment  # noqa: E402

lang = sys.argv[1] if len(sys.argv) > 1 else "en"
set_language(lang)
TZ = ZoneInfo("Europe/Istanbul")
TS = datetime(2026, 10, 11, 14, 32, 5, tzinfo=timezone.utc)
SLAT, SLON = 40.9168, 29.2883


def strip(html: str) -> str:
    return re.sub(r"</?(b|i|code|pre)>", "", html)


def show(title, ev):
    print(f"### {title}\n")
    print("```")
    print(strip(ev.to_html(TZ, SLAT, SLON)))
    print("```\n")


# ADS-B summary
ev = Event(t("evt.adsb_summary"), Category.HAVACILIK, band=t("adsb.band"), freq_mhz=1090.0,
           summary=t("adsb.summary_line", n=23, new=4) + t("adsb.nearest", d="6.8"),
           duration_s=90, signal="-9.4 dBFS", time_utc=TS,
           body="\n".join([t("adsb.total", n=23, new=4, pos=19), f"{t('common.listen_time')}: 90 {t('unit.s')}", "",
                           "• THY1KA    38000 ft   6.8 km NE  🆕", "• PGT4R     12300 ft  11.2 km E",
                           "• SXS88H     3100 ft  14.9 km SE", t("adsb.more", n=16)]))
show("ADS-B — slot summary", ev)

# nearby aircraft
ev = Event(t("adsb.name"), Category.HAVACILIK, band=t("adsb.band"), freq_mhz=1090.0,
           summary=f"{t('adsb.nearby')} THY1KA — 6.8 km", lat=40.96, lon=29.35, signal="-11.2 dBFS", time_utc=TS,
           body="\n".join([f"{t('adsb.icao')}: 4BA9C1", f"{t('adsb.callsign')}: THY1KA",
                           f"{t('adsb.altitude')}: 2900 ft  ⚠️ {t('adsb.low_alt')}", f"{t('adsb.gs')}: 182 kt",
                           f"{t('adsb.track')}: 54° (NE)", f"{t('adsb.squawk')}: 4521"]))
show("ADS-B — nearby low aircraft", ev)

# marine voice with transcript
ev = Event(t("voice.marine.name"), Category.DENIZCILIK, band="156.800 MHz · " + ("Channel 16 (Distress/Calling)" if lang == "en" else "Kanal 16 (Acil/Çağrı)"),
           freq_mhz=156.8, summary=t("voice.summary", band="156.800 MHz", s="14"), duration_s=14.2,
           signal=t("common.peak_dbfs", v="-18.3"), time_utc=TS,
           body=f"{t('voice.channel')}: " + ("Channel 16 (Distress/Calling)" if lang == "en" else "Kanal 16 (Acil/Çağrı)") +
                f"\n{t('voice.peak')}: -18.3 dBFS  ({t('voice.avg')} -24.1)",
           attachments=[Attachment("voice", "/x.ogg")])
ev.transcript = "Kıyı Emniyet, kıyı emniyet, burası Mavi Marmara, kanal altıya geçiyorum." if lang == "tr" else \
    "Coast station, coast station, this is motor vessel Blue Marmara, switching to channel six."
ev.transcript_status = "done"; ev.transcript_lang = lang
show("Marine VHF — voice recording + transcript (audio file attached as a reply)", ev)

# emergency 406
ev = Event(t("evt.emerg_406"), Category.ACIL, band=t("emerg.band"), freq_mhz=406.028,
           summary=f"⚠️ {t('emerg.label_406')} — 406.028 MHz", signal=t("common.above_floor_peak", db="21"),
           priority=0, time_utc=TS, body=f"{t('emerg.label_406')}\n{t('emerg.desc_406')}")
show("Emergency — 406 MHz distress beacon (priority alarm)", ev)

# spectrum anomaly
ev = Event(t("spec.name"), Category.TARAMA, band=t("spec.sweep", a="240", b="440"), freq_mhz=433.075,
           summary=t("spec.summary", label=t("spec.new"), f="433.075", db="18"), signal=t("common.above_floor", db="18"),
           time_utc=TS, body="\n".join([f"{t('spec.peak')}: 433.075 MHz", f"{t('spec.bw')}: ~75 kHz",
                                        f"{t('spec.power')}: -12.4 dB (+18 dB)", f"{t('spec.floor')}: -30.6 dB"]),
           attachments=[Attachment("photo", "/w.png")])
show("Spectrum — new signal (waterfall image attached)", ev)

# meteor image
ev = Event(t("meteor.name"), Category.UYDU, band=t("meteor.band"), freq_mhz=137.1,
           summary=t("meteor.summary", sat="METEOR-M2 4", n=3, el="69"), duration_s=742, time_utc=TS,
           body="\n".join([f"{t('meteor.satellite')}: METEOR-M2 4", f"{t('meteor.frequency')}: 137.100 MHz",
                           f"{t('meteor.max_el')}: 69°", f"{t('meteor.images')}: {t('meteor.images_n', n=3)}"]),
           attachments=[Attachment("photo", "/m.png")])
show("Meteor-M — LRPT pass (images attached)", ev)

# ISM new devices summary
ev = Event(t("evt.ism_new"), Category.ISM, band=t("ism.band"), summary=t("ism.summary_prefix") + t("common.items", n=5),
           time_utc=TS, body=t("ism.slot_seen", n=11) + "\n\n" + "\n".join([
               f"• {t('ism.kind.weather')}: Bresser-5in1 #112 (21.3 °C)",
               f"• {t('ism.kind.tpms')}: Schrader #a3f1c2 (231 kPa)",
               f"• {t('ism.kind.temp')}: Nexus-TH #45 (18.9 °C)",
               f"• {t('ism.kind.doorbell')}: Honeywell-ActivLink #7f3a",
               f"• {t('ism.kind.device')}: Generic-Remote #0e11"]))
show("ISM — new devices (one summary per slot)", ev)
