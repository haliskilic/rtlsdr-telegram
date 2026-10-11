"""rtlsdr-telegram — RTL-SDR multi-band monitoring, recording and Telegram notification system.

With a single RTL2832U/R860 dongle it monitors 16 targets in turn (ADS-B, AIS,
radiosondes, ISM sensors, APRS, distress beacons, GSM cell inventory, voice
bands, Meteor-M, ISS, Inmarsat, spectrum anomalies), posts events to one topic
of a Telegram group with structured headers and transcribes audio recordings.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
