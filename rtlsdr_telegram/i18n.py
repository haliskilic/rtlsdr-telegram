"""Internationalization of all user-facing (Telegram) strings.

The project ships in English by default; Turkish is available by setting
`language: tr` in config.yaml. Internal identifiers (category keys, target keys,
database values) are language-neutral so switching the language never breaks
stored data. Log messages and code comments are English.

Usage:
    from .i18n import t, set_language
    set_language("tr")
    t("hdr.band")                       -> "Frekans aralığı"
    t("adsb.summary_line", n=12, new=3) -> "12 uçak görüldü (3 yeni)"

Missing keys fall back to English, then to the key itself (so a typo is visible
in the message instead of crashing the pipeline).
"""
from __future__ import annotations

_LANG = "en"
SUPPORTED = ("en", "tr")

EN: dict[str, str] = {
    # ---- categories (keys are stored in the database) ----
    "cat.aviation": "Aviation", "cat.maritime": "Maritime", "cat.satellite": "Satellite",
    "cat.weather": "Meteorology", "cat.amateur": "Amateur Radio", "cat.ism": "ISM/Sensors",
    "cat.emergency": "Emergency", "cat.cellular": "Cellular", "cat.scan": "General Scan",
    "cat.system": "System",
    # ---- message header (spec section 5) ----
    "hdr.band": "Band", "hdr.freq": "Frequency", "hdr.time": "Time", "hdr.duration": "Duration",
    "hdr.signal": "Signal", "hdr.location": "Location", "hdr.summary": "Summary",
    "unit.s": "s", "unit.min": "min", "unit.h": "h", "unit.km": "km",
    "body.transcript": "Transcript", "body.transcript_failed": "Audio captured, no text could be extracted.",
    "geo.compass": "N,NE,E,SE,S,SW,W,NW",
    # ---- common ----
    "common.new": "New", "common.changed": "Changed", "common.more_items": "… and {n} more",
    "common.listen_time": "Listening time", "common.items": "{n} items", "common.above_floor": "+{db} dB above floor",
    "common.above_floor_peak": "+{db} dB above floor (peak)", "common.peak_dbfs": "{v} dBFS (peak)",
    "common.unknown": "unknown",
    # ---- ADS-B ----
    "adsb.name": "ADS-B Aircraft", "adsb.band": "1090 MHz ADS-B", "evt.adsb_summary": "ADS-B Summary",
    "adsb.new": "New aircraft", "adsb.nearby": "Nearby aircraft", "adsb.low_alt": "low altitude",
    "adsb.icao": "ICAO address", "adsb.callsign": "Callsign", "adsb.altitude": "Altitude",
    "adsb.gs": "Ground speed", "adsb.track": "Heading", "adsb.squawk": "Squawk",
    "adsb.summary_line": "{n} aircraft seen ({new} new)", "adsb.nearest": ", nearest {d} km",
    "adsb.total": "Total {n} aircraft ({new} new), {pos} with position",
    "adsb.more": "… and {n} more aircraft", "evt.adsb_emerg": "EMERGENCY {sq} • Aircraft",
    "sq.7500": "Hijack", "sq.7600": "Radio failure", "sq.7700": "General emergency",
    # ---- ACARS / VDL2 ----
    "acars.name": "ACARS/VDL2 Message", "acars.band": "131 MHz ACARS / 136.7–137 MHz VDL2",
    "evt.acars": "ACARS Message", "evt.vdl2": "VDL2 Message", "acars.band_acars": "131 MHz ACARS",
    "acars.band_vdl2": "136.7–137 MHz VDL2", "acars.tail": "Registration", "acars.flight": "Flight",
    "acars.label": "Label", "acars.msgno": "Message no", "acars.message": "Message",
    "evt.acars_overflow": "{label} Overflow", "acars.overflow_summary": "Slot cap exceeded: {n} more {label} messages",
    "acars.more": "… and {n} more messages",
    # ---- AIS ----
    "ais.name": "AIS Vessel", "ais.band": "161.975 / 162.025 MHz AIS", "evt.ais_summary": "AIS Summary",
    "ais.mmsi": "MMSI", "ais.vessel": "Vessel name", "ais.callsign": "Callsign", "ais.type": "Type",
    "ais.speed": "Speed", "ais.course": "Course", "ais.status": "Status", "ais.dest": "Destination",
    "ais.new": "New vessel", "ais.nearby": "Nearby vessel", "ais.summary_line": "{n} vessels seen ({new} new)",
    "ais.total": "Total {n} vessels ({new} new), {pos} with position", "ais.more": "… and {n} more vessels",
    "ais.raw_summary": "{n} AIS sentences received (raw, not decoded)",
    "ais.raw_body": "rtl_ais produced raw NMEA; install AIS-catcher for full decoding.",
    "evt.ais_sart": "EMERGENCY AIS-SART",
    "sart.970": "AIS-SART (search and rescue transmitter)", "sart.972": "MOB (man overboard) transmitter",
    "sart.974": "EPIRB-AIS distress beacon",
    "ais.sart_body": "An AIS distress transmitter broadcast was received. Verify the position if attached; contact the Coast Guard / emergency services.",
    "st.fishing": "Fishing", "st.tug": "Tug", "st.dredging": "Dredging/underwater", "st.diving": "Diving",
    "st.military": "Military", "st.sailing": "Sailing", "st.pleasure": "Pleasure craft", "st.pilot": "Pilot",
    "st.sar": "Search and rescue", "st.tender": "Port tender", "st.antipollution": "Anti-pollution",
    "st.law": "Law enforcement", "st.medical": "Medical", "st.passenger": "Passenger", "st.cargo": "Cargo",
    "st.tanker": "Tanker", "st.other": "Other", "st.type_n": "Type {n}",
    # ---- radiosonde ----
    "sonde.name": "Radiosonde", "sonde.band": "400–406 MHz radiosonde",
    "evt.sonde_carrier": "Radiosonde Carrier (candidate)",
    "sonde.carrier_summary": "Strong carrier at {f} MHz (+{db} dB) — possibly a radiosonde",
    "sonde.carrier_body": "A strong narrow-band carrier was found in the 400–406 MHz detection sweep. For full decoding (serial, position, altitude) enable radiosonde_auto_rx (config: targets.radiosonde.auto_rx.enabled).",
    "evt.sonde_launch": "Radiosonde Launch", "evt.sonde_burst": "Radiosonde Burst", "evt.sonde_descent": "Radiosonde Descent",
    "sonde.serial": "Serial", "sonde.altitude": "Altitude", "sonde.peak": "peak", "sonde.vspeed": "Vertical speed",
    "sonde.phase": "Phase", "sonde.phase.ascent": "ascent", "sonde.phase.descent": "descent",
    "sonde.phase.stable": "stable", "sonde.phase.burst": "burst", "sonde.landing": "Estimated landing",
    "sonde.landing_fmt": "≈ {lat}, {lon} (~{min} min)",
    # ---- ISM ----
    "ism.name": "ISM Sensor", "ism.band": "433.92 / 868 MHz ISM", "evt.ism_new": "ISM New Devices",
    "ism.model": "Model", "ism.id": "ID", "ism.channel": "Channel", "ism.new_prefix": "New {kind}",
    "ism.kind.tpms": "Tire sensor (TPMS)", "ism.kind.doorbell": "Doorbell/Remote", "ism.kind.weather": "Weather station",
    "ism.kind.temp": "Temperature/Humidity sensor", "ism.kind.device": "Device",
    "ism.r.temperature": "Temperature", "ism.r.humidity": "Humidity", "ism.r.pressure": "Pressure",
    "ism.r.wind": "Wind", "ism.r.wind_dir": "Wind direction", "ism.r.rain": "Rain", "ism.r.battery": "Battery",
    "ism.r.moisture": "Moisture", "ism.r.tire": "Tire", "ism.battery_ok": "ok", "ism.battery_low": "LOW ⚠️",
    "ism.slot_seen": "{n} distinct devices heard in this slot.", "ism.summary_prefix": "New devices: ",
    # ---- APRS ----
    "aprs.name": "APRS Packet", "aprs.band": "144.800 MHz APRS", "aprs.callsign": "Callsign",
    "aprs.comment": "Comment", "aprs.message": "Message", "aprs.status": "Status",
    "aprs.weather": "Contains weather data", "aprs.new": "New station",
    # ---- emergency ----
    "emerg.name": "Emergency Beacon", "emerg.band": "406 MHz / 121.5 MHz emergency",
    "evt.emerg_406": "EMERGENCY 406 MHz", "evt.emerg_121": "EMERGENCY 121.5 MHz",
    "emerg.label_406": "EPIRB/ELT/PLB distress beacon (406 MHz)",
    "emerg.desc_406": "A strong burst was detected in the 406 MHz band, which is reserved exclusively for EPIRB (ship), ELT (aircraft) and PLB (personal) distress beacons. This may be a real emergency — verify and contact the authorities if appropriate.",
    "emerg.label_121": "121.5 MHz emergency/ELT tone",
    "emerg.desc_121": "A sustained strong signal (possibly an ELT sweep tone) was detected on 121.5 MHz. Listen to the attached recording to verify.",
    "emerg.caption_121": "121.5 MHz recording",
    # ---- GSM ----
    "gsm.name": "GSM Cell", "gsm.band": "GSM 900 / 1800 (IDs only)", "evt.gsm_new": "New GSM Cell",
    "evt.gsm_changed": "GSM Cell Changed", "gsm.operator": "Operator", "gsm.cid": "Cell ID", "gsm.lac": "LAC",
    "gsm.mccmnc": "MCC/MNC", "gsm.arfcn": "ARFCN", "gsm.power": "Power",
    "gsm.summary": "{what} cell — {op}, CID {cid}",
    # ---- voice bands ----
    "voice.amateur.name": "Amateur Radio Voice", "voice.amateur.band": "144–146 / 430–440 MHz amateur",
    "voice.airband.name": "Airband Voice", "voice.airband.band": "118–137 MHz airband (AM)",
    "voice.marine.name": "Marine VHF Voice", "voice.marine.band": "156–162 MHz marine VHF",
    "voice.cbpmr.name": "CB / PMR446 Voice", "voice.cbpmr.band": "26–28 MHz CB / 446 MHz PMR",
    "voice.channel": "Channel", "voice.peak": "Peak level", "voice.avg": "avg",
    "voice.summary": "{band} — {s} s transmission", "voice.scan_active": "active in scan (+{db} dB)",
    # ---- channel maps ----
    "ch.channel": "Channel", "ch.cb": "CB Channel", "ch.pmr": "PMR Channel", "ch.coast": "[coast]",
    "ch.m16": "Distress/Calling", "ch.m70": "DSC (digital)", "ch.m13": "Bridge-to-bridge safety",
    "ch.m6": "Ship-ship / SAR", "ch.m12": "Port/VTS", "ch.m14": "Port/VTS", "ch.m9": "Calling (alt)",
    "ch.m10": "Port operations", "ch.m11": "Port operations", "ch.m67": "SAR / small craft",
    "ch.m72": "Ship-ship", "ch.m73": "Ship-ship", "ch.m77": "Ship-ship", "ch.m8": "Ship-ship",
    "ch.m15": "On-board", "ch.m17": "On-board", "ch.ais1": "AIS 1 (87B)", "ch.ais2": "AIS 2 (88B)",
    "ch.cb9": "Emergency", "ch.cb19": "Highway",
    "ch.air1215": "Guard (emergency)", "ch.air12345": "Air-to-air", "ch.air243": "Military guard",
    "ch.am1455": "2m calling (simplex)", "ch.am1448": "APRS", "ch.am1458": "ISS voice/SSTV",
    "ch.am145825": "ISS packet", "ch.am4335": "70cm calling (simplex)", "ch.am1443": "2m SSB calling",
    # ---- Meteor-M ----
    "meteor.name": "Meteor-M Image", "meteor.band": "137 MHz Meteor-M LRPT",
    "meteor.no_image_summary": "{sat} pass complete, no image received",
    "meteor.no_image_body": "The pass was monitored but no decodable LRPT image was produced (low elevation, weak signal or antenna orientation). Max elevation: {el}°.",
    "meteor.summary": "{sat} pass — {n} images (max {el}°)",
    "meteor.satellite": "Satellite", "meteor.frequency": "Frequency", "meteor.max_el": "Max elevation",
    "meteor.images": "Images", "meteor.images_n": "{n} files",
    # ---- ISS ----
    "iss.name": "ISS", "iss.band": "145.800/145.825 MHz ISS", "evt.iss_voice": "ISS Voice",
    "evt.iss_sstv": "ISS SSTV/Voice", "evt.iss_packet": "ISS Packet", "evt.iss_pass": "ISS Pass",
    "iss.summary": "ISS pass — {s} s transmission (max {el}°)", "iss.sstv_count": ", {n} SSTV images",
    "iss.max_el": "Max elevation", "iss.peak": "Peak level",
    "iss.no_signal_summary": "ISS pass monitored, no transmission (max {el}°)",
    "iss.no_signal_body": "The ISS pass window was monitored but no signal was captured. ISS voice/SSTV is only transmitted during scheduled events.",
    "iss.packet_summary": "ISS digipeater packet: {src}", "iss.caption": "ISS 145.800 MHz", "iss.sstv_caption": "ISS SSTV",
    # ---- Inmarsat ----
    "inmarsat.name": "Inmarsat STD-C", "inmarsat.band": "~1.5 GHz Inmarsat (L-band)",
    "evt.inmarsat_msg": "Inmarsat Message", "evt.inmarsat_setup": "Inmarsat Setup",
    "inmarsat.setup_summary": "Inmarsat is active but no decoder command is configured",
    "inmarsat.setup_body": "Inmarsat STD-C/AERO needs extra hardware: an L-band antenna + LNA (usually bias-tee powered). Use SatDump (pipeline inmarsat_std_c) or JAERO as the decoder and put the command into <code>targets.inmarsat.decoder_cmd</code>. Without the hardware leave <code>active: false</code>.",
    # ---- spectrum ----
    "spec.name": "Spectrum Anomaly", "spec.band": "24–1766 MHz spectrum (excl. FM/TV)",
    "spec.new": "New signal", "spec.ongoing": "Ongoing signal", "spec.peak": "Peak frequency",
    "spec.bw": "Bandwidth", "spec.power": "Power", "spec.floor": "Noise floor", "spec.first_seen": "First seen",
    "spec.seen_n": "({n}. time)", "spec.summary": "{label} @ {f} MHz (+{db} dB)", "spec.sweep": "{a}–{b} MHz sweep",
    "spec.caption": "Waterfall: {f} MHz", "spec.plot_x": "Frequency (MHz)", "spec.plot_y": "Time (sweep)",
    "spec.plot_title": "Spectrum waterfall @ {f} MHz",
    # ---- scheduler / ad-hoc ----
    "evt.adhoc": "Ad-hoc Scan", "adhoc.none": "{band} — listened {s} s, no activity",
    "adhoc.summary": "{band} — {s} s transmission", "status.idle": "idle",
    "eta.sec": "in {n} s", "eta.min": "in {n} min", "eta.h": "in {h} h {m} min",
    "status.pass_eta": "{name} pass {eta}",
    # ---- system / app ----
    "evt.system_started": "System Started", "sys.started_title": "RTL-SDR monitoring system started",
    "sys.station": "Station", "sys.platform": "Platform", "sys.dongle": "Dongle",
    "sys.dongle_missing": "not found — is it plugged in?", "sys.active_targets": "Active targets",
    "sys.transcription": "Transcription", "sys.off": "off", "sys.sat_pred": "Satellite prediction",
    "sys.sat_pred_off": "off (skyfield missing)", "sys.missing_tools": "⚠️ Missing tools",
    "sys.help_hint": "Commands: /help", "sys.started_summary": "System started",
    "sys.stopping": "RTL-SDR monitoring system stopping", "evt.heartbeat": "Heartbeat",
    "sys.heartbeat_body": "Dongle: {d} · Now: {cur} · {n} events in the last hour · Queue {q}",
    "evt.disk_warning": "Disk Space Warning",
    "sys.disk_warning_summary": "Only {pct}% disk free — {n} oldest recordings pruned",
    "sys.disk_warning_body": "Free disk space dropped below {min}%. The oldest recording files were deleted automatically and new recordings are paused until space is available. Consider lowering paths.retention_days.",
    "evt.test": "Test Message", "sys.test_body": "Connection works.",
    # ---- daily summary ----
    "evt.summary": "Daily Summary", "sum.title": "Daily Summary", "sum.period": "Covered period: last {h} hours",
    "sum.total": "Total events", "sum.by_cat": "By category", "sum.top_types": "Most active event types",
    "sum.unique": "Unique detections", "sum.u.aircraft": "aircraft", "sum.u.vessels": "vessels",
    "sum.u.ism": "ISM devices", "sum.u.aprs": "APRS stations", "sum.u.cells": "GSM cells",
    "sum.new_period": "New this period", "sum.new_devices": "{n} new ISM devices", "sum.new_cells": "{n} new GSM cells",
    "sum.new_anom": "{n} new spectrum anomalies", "sum.audio": "Total audio recorded", "sum.images": "Satellite/images",
    "sum.top_events": "Top {n} notable events", "sum.uptime": "Uptime", "sum.errors": "Errors",
    "sum.summary_line": "{n} events, {audio} audio, {img} images", "sum.csv_caption": "Event export (CSV)",
    "sum.generating": "📅 Generating the daily summary…", "sum.failed": "Summary failed: {e}",
    # ---- commands ----
    "cmd.unauthorized": "⛔ Not authorized. (your user id: <code>{uid}</code>)",
    "cmd.unauthorized_hint": "\nAdd this id to telegram.admins in config.yaml and restart the service.",
    "cmd.status_title": "📊 <b>System Status</b>", "cmd.dongle_ok": "📡 Dongle: ✅ {d}",
    "cmd.dongle_missing": "📡 Dongle: ❌ not found (plugged in?)", "cmd.now": "🎯 Now: <b>{cur}</b>",
    "cmd.listening": "   └ listening: {f} ({s} s)", "cmd.next": "⏭️ Next: {n}", "cmd.next_pass": "🛰️ Satellite: {p}",
    "cmd.queue": "📨 Queue: {n} messages pending", "cmd.active": "✅ Active targets: {a}/{t}",
    "cmd.muted": "🔇 Muted: {m}", "cmd.boosted": "⚡ Prioritized: {b}", "cmd.cpu": "🖥️ CPU: {cpu}  ·  RAM: {mem}",
    "cmd.temp": "🌡️ Temperature: {t}", "cmd.load": "📈 Load: {l}", "cmd.uptime": "⏱️ Uptime: {u}",
    "cmd.scan_usage": "Usage: <code>/scan 145.500 [seconds] [am|fm]</code>",
    "cmd.scan_badfreq": "Invalid frequency. Example: <code>/scan 145.500</code>",
    "cmd.scan_range": "Frequency must be between 24 and 1766 MHz.",
    "cmd.scan_blacklist": "⚠️ {f} MHz is blacklisted (FM/TV). Trying anyway…",
    "cmd.scan_ack": "🎧 Listening on {f} MHz ({m}) for ~{s} s; any activity will be posted here.",
    "cmd.mute_usage": "Usage: <code>/mute Aviation</code>\nCategories: {cats}",
    "cmd.muted_ok": "🔇 Category '{c}' muted. Unmute: <code>/unmute {raw}</code>",
    "cmd.unknown_cat": "Unknown category: {c}", "cmd.unmute_usage": "Usage: <code>/unmute Aviation</code>",
    "cmd.unmuted_ok": "🔊 Category '{c}' is active again.",
    "cmd.prio_usage": "Usage: <code>/priority adsb</code>\nTargets: {keys}",
    "cmd.prio_ok": "⚡ '{k}' moved to the front of the scan cycle ({m} min).", "cmd.unknown_target": "Unknown target: {k}",
    "cmd.no_recordings": "No audio recordings yet.", "cmd.resending": "🔁 Sending the last {n} recordings…",
    "cmd.list_title": "📋 <b>Target List</b>", "cmd.list_due": " (due)", "cmd.list_in": " ({s}s)",
    "cmd.list_notool": " ⚠️tool missing",
    "cmd.list_legend": "🟢 active · ⚪ off · 🔇 muted · ⏰ scheduled · 🔄 opportunistic",
    "cmd.passes_title": "🛰️ <b>Upcoming passes</b> (next {h} h)",
    "cmd.passes_none": "No suitable passes in the next {h} hours (or TLE/skyfield unavailable).",
    "cmd.passes_failed": "Pass calculation failed: {e}", "cmd.pass_line": "• {sat}: {r}–{s}  max {el}°  ({m} min)",
    "cmd.help": (
        "🤖 <b>RTL-SDR Monitor Bot — Commands</b>\n\n"
        "/status (/durum) — system status, current band, CPU/temperature, uptime\n"
        "/list (/liste) — all targets and their state\n"
        "/scan <code>145.5 [s] [am|fm]</code> (/tara) — listen to a frequency temporarily\n"
        "/mute <code>&lt;category&gt;</code> (/sustur) — mute a category\n"
        "/unmute <code>&lt;category&gt;</code> (/ac) — unmute a category\n"
        "/priority <code>&lt;target&gt;</code> (/oncelik) — move a target to the front\n"
        "/summary (/ozet) — generate the daily summary now\n"
        "/recordings <code>[n]</code> (/kayitlar) — resend the last n recordings\n"
        "/passes <code>[hours]</code> (/gecisler) — upcoming satellite/ISS passes\n"
        "/help (/yardim) — this list\n\n"
        "Categories: {cats}"),
    # ---- recordings caption ----
    "rec.caption": "{ch} · {f} MHz\n{when} · {s} s · {sig}",
    # ---- transcription prompts (keyed by category key) ----
    "asr.prompt.aviation": "Tower, approach, runway, cleared for takeoff, cleared to land, QNH, squawk, flight level, heading, descend, climb, ATIS.",
    "asr.prompt.maritime": "Channel sixteen, Mayday, Pan Pan, Securite, coast guard, port, vessel, captain, anchor, course, knots.",
    "asr.prompt.amateur": "QSO, QTH, QSL, 73, repeater, callsign, CQ, roger, over.",
    "asr.prompt.emergency": "Mayday, Pan Pan, emergency, 121.5, help.",
}

TR: dict[str, str] = {
    "cat.aviation": "Havacılık", "cat.maritime": "Denizcilik", "cat.satellite": "Uydu",
    "cat.weather": "Meteoroloji", "cat.amateur": "Amatör Telsiz", "cat.ism": "ISM/Sensör",
    "cat.emergency": "Acil Durum", "cat.cellular": "Hücresel", "cat.scan": "Genel Tarama",
    "cat.system": "Sistem",
    "hdr.band": "Frekans aralığı", "hdr.freq": "Yakalanan frekans", "hdr.time": "Zaman", "hdr.duration": "Süre",
    "hdr.signal": "Sinyal gücü", "hdr.location": "Konum", "hdr.summary": "Özet",
    "unit.s": "sn", "unit.min": "dk", "unit.h": "sa", "unit.km": "km",
    "body.transcript": "Transkripsiyon", "body.transcript_failed": "Ses alındı, metin çıkarılamadı.",
    "geo.compass": "K,KD,D,GD,G,GB,B,KB",
    "common.new": "Yeni", "common.changed": "Değişen", "common.more_items": "… ve {n} öge daha",
    "common.listen_time": "Dinleme süresi", "common.items": "{n} öge", "common.above_floor": "+{db} dB taban üstü",
    "common.above_floor_peak": "+{db} dB taban üstü (tepe)", "common.peak_dbfs": "{v} dBFS (tepe)",
    "common.unknown": "bilinmeyen",
    "adsb.name": "ADS-B Uçak", "adsb.band": "1090 MHz ADS-B", "evt.adsb_summary": "ADS-B Özet",
    "adsb.new": "Yeni uçak", "adsb.nearby": "Yakın uçak", "adsb.low_alt": "alçak uçuş",
    "adsb.icao": "ICAO adresi", "adsb.callsign": "Çağrı kodu", "adsb.altitude": "İrtifa",
    "adsb.gs": "Yer hızı", "adsb.track": "Yön", "adsb.squawk": "Squawk",
    "adsb.summary_line": "{n} uçak görüldü ({new} yeni)", "adsb.nearest": ", en yakın {d} km",
    "adsb.total": "Toplam {n} uçak ({new} yeni), konumlu {pos}",
    "adsb.more": "… ve {n} uçak daha", "evt.adsb_emerg": "ACİL {sq} • Uçak",
    "sq.7500": "Uçak kaçırma (hijack)", "sq.7600": "Telsiz arızası", "sq.7700": "Genel acil durum",
    "acars.name": "ACARS/VDL2 Mesaj", "acars.band": "131 MHz ACARS / 136.7–137 MHz VDL2",
    "evt.acars": "ACARS Mesaj", "evt.vdl2": "VDL2 Mesaj", "acars.band_acars": "131 MHz ACARS",
    "acars.band_vdl2": "136.7–137 MHz VDL2", "acars.tail": "Kuyruk no", "acars.flight": "Sefer",
    "acars.label": "Etiket", "acars.msgno": "Mesaj no", "acars.message": "Mesaj",
    "evt.acars_overflow": "{label} Özet", "acars.overflow_summary": "Slot sınırı aşıldı: {n} ek {label} mesajı",
    "acars.more": "… ve {n} mesaj daha",
    "ais.name": "AIS Gemi", "ais.band": "161.975 / 162.025 MHz AIS", "evt.ais_summary": "AIS Özet",
    "ais.mmsi": "MMSI", "ais.vessel": "Gemi adı", "ais.callsign": "Çağrı işr.", "ais.type": "Tip",
    "ais.speed": "Hız", "ais.course": "Rota", "ais.status": "Durum", "ais.dest": "Varış",
    "ais.new": "Yeni gemi", "ais.nearby": "Yakın gemi", "ais.summary_line": "{n} gemi görüldü ({new} yeni)",
    "ais.total": "Toplam {n} gemi ({new} yeni), konumlu {pos}", "ais.more": "… ve {n} gemi daha",
    "ais.raw_summary": "{n} AIS cümlesi alındı (ham, çözülmedi)",
    "ais.raw_body": "rtl_ais ham NMEA üretti; tam çözümleme için AIS-catcher kurun.",
    "evt.ais_sart": "ACİL AIS-SART",
    "sart.970": "AIS-SART (arama-kurtarma vericisi)", "sart.972": "MOB (denize adam düştü) vericisi",
    "sart.974": "EPIRB-AIS acil durum vericisi",
    "ais.sart_body": "AIS üzerinden acil durum vericisi yayını alındı. Konum ekteyse doğrulayın; Sahil Güvenlik 158 / Acil 112.",
    "st.fishing": "Balıkçı", "st.tug": "Römorkör", "st.dredging": "Tarama/sualtı", "st.diving": "Dalış",
    "st.military": "Askeri", "st.sailing": "Yelkenli", "st.pleasure": "Tekne", "st.pilot": "Pilot",
    "st.sar": "Arama-kurtarma", "st.tender": "Liman hizmet", "st.antipollution": "Kirlilikle mücadele",
    "st.law": "Kolluk", "st.medical": "Tıbbi", "st.passenger": "Yolcu", "st.cargo": "Kargo",
    "st.tanker": "Tanker", "st.other": "Diğer", "st.type_n": "Tip {n}",
    "sonde.name": "Radyosonda", "sonde.band": "400–406 MHz radyosonda",
    "evt.sonde_carrier": "Radyosonda Taşıyıcı (aday)",
    "sonde.carrier_summary": "{f} MHz'de güçlü taşıyıcı (+{db} dB) — radyosonda olabilir",
    "sonde.carrier_body": "400–406 MHz tespit taramasında güçlü dar-bant taşıyıcı bulundu. Tam çözümleme (seri no, konum, irtifa) için radiosonde_auto_rx'i etkinleştirin (config: targets.radiosonde.auto_rx.enabled).",
    "evt.sonde_launch": "Radyosonda Kalkış", "evt.sonde_burst": "Radyosonda Patlama", "evt.sonde_descent": "Radyosonda Alçalış",
    "sonde.serial": "Seri no", "sonde.altitude": "İrtifa", "sonde.peak": "tepe", "sonde.vspeed": "Dikey hız",
    "sonde.phase": "Faz", "sonde.phase.ascent": "yükseliş", "sonde.phase.descent": "alçalış",
    "sonde.phase.stable": "sabit", "sonde.phase.burst": "patlama", "sonde.landing": "Tahmini düşüş",
    "sonde.landing_fmt": "≈ {lat}, {lon} (~{min} dk sonra)",
    "ism.name": "ISM Sensör", "ism.band": "433.92 / 868 MHz ISM", "evt.ism_new": "ISM Yeni Cihazlar",
    "ism.model": "Model", "ism.id": "Kimlik", "ism.channel": "Kanal", "ism.new_prefix": "Yeni {kind}",
    "ism.kind.tpms": "Lastik (TPMS)", "ism.kind.doorbell": "Kapı zili/Kumanda", "ism.kind.weather": "Hava istasyonu",
    "ism.kind.temp": "Sıcaklık/Nem sensörü", "ism.kind.device": "Cihaz",
    "ism.r.temperature": "Sıcaklık", "ism.r.humidity": "Nem", "ism.r.pressure": "Basınç",
    "ism.r.wind": "Rüzgar", "ism.r.wind_dir": "Rüzgar yönü", "ism.r.rain": "Yağış", "ism.r.battery": "Pil",
    "ism.r.moisture": "Nem/toprak", "ism.r.tire": "Lastik", "ism.battery_ok": "iyi", "ism.battery_low": "ZAYIF ⚠️",
    "ism.slot_seen": "Bu slotta {n} farklı cihaz duyuldu.", "ism.summary_prefix": "Yeni cihaz: ",
    "aprs.name": "APRS Paket", "aprs.band": "144.800 MHz APRS", "aprs.callsign": "Çağrı işareti",
    "aprs.comment": "Yorum", "aprs.message": "Mesaj", "aprs.status": "Durum",
    "aprs.weather": "Hava verisi içeriyor", "aprs.new": "Yeni istasyon",
    "emerg.name": "Acil Verici", "emerg.band": "406 MHz / 121.5 MHz acil",
    "evt.emerg_406": "ACİL 406 MHz", "evt.emerg_121": "ACİL 121.5 MHz",
    "emerg.label_406": "EPIRB/ELT/PLB acil durum vericisi (406 MHz)",
    "emerg.desc_406": "406 MHz bandında güçlü patlama tespit edildi. Bu bant yalnızca EPIRB (gemi), ELT (uçak) ve PLB (kişisel) acil durum vericilerine ayrılmıştır. Gerçek bir acil durum olabilir — doğrulayın ve gerekirse yetkilileri arayın (AKUB/112).",
    "emerg.label_121": "121.5 MHz acil/ELT tonu",
    "emerg.desc_121": "121.5 MHz'de sürekli güçlü sinyal (ELT süpürme tonu olabilir) tespit edildi. Ekli kaydı dinleyerek doğrulayın.",
    "emerg.caption_121": "121.5 MHz kaydı",
    "gsm.name": "GSM Hücre", "gsm.band": "GSM 900 / 1800 (yalnız kimlik)", "evt.gsm_new": "Yeni GSM Hücre",
    "evt.gsm_changed": "GSM Hücre Değişti", "gsm.operator": "Operatör", "gsm.cid": "Cell ID", "gsm.lac": "LAC",
    "gsm.mccmnc": "MCC/MNC", "gsm.arfcn": "ARFCN", "gsm.power": "Güç",
    "gsm.summary": "{what} hücre — {op}, CID {cid}",
    "voice.amateur.name": "Amatör Telsiz Ses", "voice.amateur.band": "144–146 / 430–440 MHz amatör",
    "voice.airband.name": "Hava Bandı Ses", "voice.airband.band": "118–137 MHz hava bandı (AM)",
    "voice.marine.name": "Deniz VHF Ses", "voice.marine.band": "156–162 MHz deniz VHF",
    "voice.cbpmr.name": "CB / PMR446 Ses", "voice.cbpmr.band": "26–28 MHz CB / 446 MHz PMR",
    "voice.channel": "Kanal", "voice.peak": "Tepe seviye", "voice.avg": "ort.",
    "voice.summary": "{band} — {s} sn yayın", "voice.scan_active": "taramada aktif (+{db} dB)",
    "ch.channel": "Kanal", "ch.cb": "CB Kanal", "ch.pmr": "PMR Kanal", "ch.coast": "[sahil]",
    "ch.m16": "Acil/Çağrı", "ch.m70": "DSC (dijital)", "ch.m13": "Köprü-köprü emniyet",
    "ch.m6": "Gemi-gemi / SAR", "ch.m12": "Liman/VTS", "ch.m14": "Liman/VTS", "ch.m9": "Çağrı (yedek)",
    "ch.m10": "Liman operasyon", "ch.m11": "Liman operasyon", "ch.m67": "SAR / Küçük tekne",
    "ch.m72": "Gemi-gemi", "ch.m73": "Gemi-gemi", "ch.m77": "Gemi-gemi", "ch.m8": "Gemi-gemi",
    "ch.m15": "Gemi içi", "ch.m17": "Gemi içi", "ch.ais1": "AIS 1 (87B)", "ch.ais2": "AIS 2 (88B)",
    "ch.cb9": "Acil", "ch.cb19": "Karayolu",
    "ch.air1215": "Acil (Guard)", "ch.air12345": "Hava-hava", "ch.air243": "Askeri acil",
    "ch.am1455": "2m çağrı (simpleks)", "ch.am1448": "APRS", "ch.am1458": "ISS ses/SSTV",
    "ch.am145825": "ISS paket", "ch.am4335": "70cm çağrı (simpleks)", "ch.am1443": "2m SSB çağrı",
    "meteor.name": "Meteor-M Görüntü", "meteor.band": "137 MHz Meteor-M LRPT",
    "meteor.no_image_summary": "{sat} geçişi tamamlandı, görüntü alınamadı",
    "meteor.no_image_body": "Geçiş dinlendi ancak çözülebilir LRPT görüntüsü üretilmedi (düşük irtifa, zayıf sinyal veya anten yönü). Maksimum irtifa: {el}°.",
    "meteor.summary": "{sat} geçişi — {n} görüntü (maks {el}°)",
    "meteor.satellite": "Uydu", "meteor.frequency": "Frekans", "meteor.max_el": "Maks. irtifa",
    "meteor.images": "Görüntü", "meteor.images_n": "{n} adet",
    "iss.name": "ISS", "iss.band": "145.800/145.825 MHz ISS", "evt.iss_voice": "ISS Ses",
    "evt.iss_sstv": "ISS SSTV/Ses", "evt.iss_packet": "ISS Paket", "evt.iss_pass": "ISS Geçiş",
    "iss.summary": "ISS geçişi — {s} sn yayın (maks {el}°)", "iss.sstv_count": ", {n} SSTV görüntüsü",
    "iss.max_el": "Maks. irtifa", "iss.peak": "Tepe seviye",
    "iss.no_signal_summary": "ISS geçişi dinlendi, yayın yok (maks {el}°)",
    "iss.no_signal_body": "ISS geçiş penceresi dinlendi ancak sinyal yakalanmadı. ISS sesi/SSTV'si yalnızca planlı etkinliklerde yayınlanır.",
    "iss.packet_summary": "ISS dijipiter paketi: {src}", "iss.caption": "ISS 145.800 MHz", "iss.sstv_caption": "ISS SSTV",
    "inmarsat.name": "Inmarsat STD-C", "inmarsat.band": "~1.5 GHz Inmarsat (L-bant)",
    "evt.inmarsat_msg": "Inmarsat Mesaj", "evt.inmarsat_setup": "Inmarsat Kurulum",
    "inmarsat.setup_summary": "Inmarsat aktif ama çözücü komutu tanımlı değil",
    "inmarsat.setup_body": "Inmarsat STD-C/AERO için ek donanım gerekir: L-bant anten + LNA (genelde bias-tee ile beslenir). Çözücü olarak SatDump (inmarsat_std_c ardışık düzeni) veya JAERO kullanıp komutu <code>targets.inmarsat.decoder_cmd</code> alanına yazın. Donanım yoksa <code>active: false</code> bırakın.",
    "spec.name": "Spektrum Anomali", "spec.band": "24–1766 MHz spektrum (FM/TV hariç)",
    "spec.new": "Yeni sinyal", "spec.ongoing": "Süregelen sinyal", "spec.peak": "Tepe frekans",
    "spec.bw": "Bant genişliği", "spec.power": "Güç", "spec.floor": "Gürültü tabanı", "spec.first_seen": "İlk görülme",
    "spec.seen_n": "({n}. kez)", "spec.summary": "{label} @ {f} MHz (+{db} dB)", "spec.sweep": "{a}–{b} MHz tarama",
    "spec.caption": "Şelale: {f} MHz", "spec.plot_x": "Frekans (MHz)", "spec.plot_y": "Zaman (tarama)",
    "spec.plot_title": "Spektrum şelalesi @ {f} MHz",
    "evt.adhoc": "Geçici Tarama", "adhoc.none": "{band} — {s} sn dinlendi, etkinlik yok",
    "adhoc.summary": "{band} — {s} sn yayın", "status.idle": "boşta",
    "eta.sec": "{n} sn sonra", "eta.min": "{n} dk sonra", "eta.h": "{h} sa {m} dk sonra",
    "status.pass_eta": "{name} geçişi {eta}",
    "evt.system_started": "Sistem Başladı", "sys.started_title": "RTL-SDR İzleme sistemi başladı",
    "sys.station": "İstasyon", "sys.platform": "Platform", "sys.dongle": "Dongle",
    "sys.dongle_missing": "bulunamadı — takılı mı?", "sys.active_targets": "Aktif hedef",
    "sys.transcription": "Transkripsiyon", "sys.off": "kapalı", "sys.sat_pred": "Uydu tahmini",
    "sys.sat_pred_off": "kapalı (skyfield yok)", "sys.missing_tools": "⚠️ Araç eksik",
    "sys.help_hint": "Komutlar için /yardim", "sys.started_summary": "Sistem başlatıldı",
    "sys.stopping": "RTL-SDR İzleme sistemi durduruluyor", "evt.heartbeat": "Kalp Atışı",
    "sys.heartbeat_body": "Dongle: {d} · Şu an: {cur} · Son 1 saatte {n} olay · Kuyruk {q}",
    "evt.disk_warning": "Disk Alanı Uyarısı",
    "sys.disk_warning_summary": "Diskte yalnız %{pct} boş — en eski {n} kayıt silindi",
    "sys.disk_warning_body": "Boş disk alanı %{min} altına düştü. En eski kayıt dosyaları otomatik silindi; alan açılana kadar yeni kayıt alınmıyor. paths.retention_days değerini düşürmeyi düşünün.",
    "evt.test": "Test Mesajı", "sys.test_body": "Bağlantı çalışıyor.",
    "evt.summary": "Günlük Özet", "sum.title": "Günlük Özet", "sum.period": "Kapsanan süre: son {h} saat",
    "sum.total": "Toplam olay", "sum.by_cat": "Kategori bazında", "sum.top_types": "En aktif olay türleri",
    "sum.unique": "Benzersiz tespitler", "sum.u.aircraft": "uçak", "sum.u.vessels": "gemi",
    "sum.u.ism": "ISM cihaz", "sum.u.aprs": "APRS ist.", "sum.u.cells": "GSM hücre",
    "sum.new_period": "Yeni bu dönem", "sum.new_devices": "{n} yeni ISM cihaz", "sum.new_cells": "{n} yeni GSM hücre",
    "sum.new_anom": "{n} yeni spektrum anomali", "sum.audio": "Toplam ses kaydı", "sum.images": "Uydu/görüntü",
    "sum.top_events": "En dikkat çeken {n} olay", "sum.uptime": "Çalışma süresi", "sum.errors": "Hata",
    "sum.summary_line": "{n} olay, {audio} ses, {img} görüntü", "sum.csv_caption": "Olay dökümü (CSV)",
    "sum.generating": "📅 Günlük özet üretiliyor…", "sum.failed": "Özet üretilemedi: {e}",
    "cmd.unauthorized": "⛔ Yetkiniz yok. (kullanıcı kimliğiniz: <code>{uid}</code>)",
    "cmd.unauthorized_hint": "\nconfig.yaml → telegram.admins listesine bu kimliği ekleyip servisi yeniden başlatın.",
    "cmd.status_title": "📊 <b>Sistem Durumu</b>", "cmd.dongle_ok": "📡 Dongle: ✅ {d}",
    "cmd.dongle_missing": "📡 Dongle: ❌ bulunamadı (takılı mı?)", "cmd.now": "🎯 Şu an: <b>{cur}</b>",
    "cmd.listening": "   └ dinlenen: {f} ({s} sn)", "cmd.next": "⏭️ Sıradaki: {n}", "cmd.next_pass": "🛰️ Uydu: {p}",
    "cmd.queue": "📨 Kuyruk: {n} mesaj bekliyor", "cmd.active": "✅ Aktif hedef: {a}/{t}",
    "cmd.muted": "🔇 Susturulan: {m}", "cmd.boosted": "⚡ Öncelikli: {b}", "cmd.cpu": "🖥️ CPU: {cpu}  ·  RAM: {mem}",
    "cmd.temp": "🌡️ Sıcaklık: {t}", "cmd.load": "📈 Yük: {l}", "cmd.uptime": "⏱️ Çalışma süresi: {u}",
    "cmd.scan_usage": "Kullanım: <code>/tara 145.500 [süre_sn] [am|fm]</code>",
    "cmd.scan_badfreq": "Geçersiz frekans. Örnek: <code>/tara 145.500</code>",
    "cmd.scan_range": "Frekans 24–1766 MHz aralığında olmalı.",
    "cmd.scan_blacklist": "⚠️ {f} MHz kara listede (FM/TV). Yine de deneniyor…",
    "cmd.scan_ack": "🎧 {f} MHz ({m}) ~{s} sn dinlenecek; etkinlik olursa kaydı buraya göndereceğim.",
    "cmd.mute_usage": "Kullanım: <code>/sustur Havacılık</code>\nKategoriler: {cats}",
    "cmd.muted_ok": "🔇 '{c}' kategorisi susturuldu. Geri açmak: <code>/ac {raw}</code>",
    "cmd.unknown_cat": "Bilinmeyen kategori: {c}", "cmd.unmute_usage": "Kullanım: <code>/ac Havacılık</code>",
    "cmd.unmuted_ok": "🔊 '{c}' kategorisi tekrar aktif.",
    "cmd.prio_usage": "Kullanım: <code>/oncelik adsb</code>\nHedefler: {keys}",
    "cmd.prio_ok": "⚡ '{k}' tarama döngüsünde öne alındı ({m} dk).", "cmd.unknown_target": "Bilinmeyen hedef: {k}",
    "cmd.no_recordings": "Henüz ses kaydı yok.", "cmd.resending": "🔁 Son {n} kayıt gönderiliyor…",
    "cmd.list_title": "📋 <b>Hedef Listesi</b>", "cmd.list_due": " (sırada)", "cmd.list_in": " ({s}sn)",
    "cmd.list_notool": " ⚠️araç yok",
    "cmd.list_legend": "🟢 aktif · ⚪ kapalı · 🔇 susturulmuş · ⏰ zamanlanmış · 🔄 fırsatçı",
    "cmd.passes_title": "🛰️ <b>Yaklaşan geçişler</b> (önümüzdeki {h} sa)",
    "cmd.passes_none": "Önümüzdeki {h} saatte uygun geçiş yok (ya da TLE/skyfield yok).",
    "cmd.passes_failed": "Geçiş hesabı başarısız: {e}", "cmd.pass_line": "• {sat}: {r}–{s}  maks {el}°  ({m} dk)",
    "cmd.help": (
        "🤖 <b>RTL-SDR İzleme Botu — Komutlar</b>\n\n"
        "/durum (/status) — sistem durumu, dinlenen bant, CPU/sıcaklık, uptime\n"
        "/liste (/list) — tüm hedefler ve durumları\n"
        "/tara <code>145.5 [sn] [am|fm]</code> (/scan) — frekansı geçici dinle\n"
        "/sustur <code>&lt;kategori&gt;</code> (/mute) — kategoriyi sustur\n"
        "/ac <code>&lt;kategori&gt;</code> (/unmute) — kategoriyi geri aç\n"
        "/oncelik <code>&lt;hedef&gt;</code> (/priority) — hedefi öne al\n"
        "/ozet (/summary) — günlük özeti hemen üret\n"
        "/kayitlar <code>[n]</code> (/recordings) — son n kaydı yeniden gönder\n"
        "/gecisler <code>[saat]</code> (/passes) — yaklaşan uydu/ISS geçişleri\n"
        "/yardim (/help) — bu liste\n\n"
        "Kategoriler: {cats}"),
    "rec.caption": "{ch} · {f} MHz\n{when} · {s} sn · {sig}",
    "asr.prompt.aviation": "Tower, approach, runway, cleared for takeoff, cleared to land, QNH, squawk, flight level, heading, descend, climb, ATIS, kule, pist, iniş, kalkış.",
    "asr.prompt.maritime": "Kanal 16, Mayday, Pan Pan, Securite, Sahil Güvenlik, liman, gemi, kaptan, demir, rota, knot, channel sixteen, coast guard, vessel.",
    "asr.prompt.amateur": "QSO, QTH, QSL, 73, röle, çağrı işareti, TA1, TA2, YM, CQ, roger, over.",
    "asr.prompt.emergency": "Mayday, Pan Pan, emergency, 121.5, acil, yardım.",
}

_TABLES = {"en": EN, "tr": TR}


def set_language(lang: str | None) -> str:
    """Select the UI language ('en' or 'tr'). Unknown values fall back to English."""
    global _LANG
    lang = (lang or "en").strip().lower()[:2]
    _LANG = lang if lang in _TABLES else "en"
    return _LANG


def get_language() -> str:
    return _LANG


def t(key: str, **kwargs) -> str:
    """Translate `key` in the active language, formatting with kwargs."""
    table = _TABLES.get(_LANG, EN)
    text = table.get(key) or EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def compass_labels() -> list[str]:
    return t("geo.compass").split(",")
