"""rtlsdr-telegram — RTL-SDR çok bantlı izleme, kayıt ve Telegram bildirim sistemi.

Tek bir RTL2832U/R860 dongle ile 16 farklı hedefi (ADS-B, AIS, radyosonda, ISM,
APRS, acil durum vericileri, GSM envanteri, ses bantları, Meteor-M, ISS, Inmarsat,
spektrum anomali) sırayla izler; olayları Telegram grubunun tek bir topic'ine
yapılandırılmış başlıklarla gönderir; ses kayıtlarını otomatik yazıya döker.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
