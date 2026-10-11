# rtlsdr-telegram

**Tek bir RTL-SDR dongle ile çok bantlı radyo izleme; her şey tek bir Telegram topic'ine düşer.**
Uçaklar, gemiler, meteoroloji balonları, kablosuz sensörler, amatör paket radyo, acil durum
vericileri, GSM hücre envanteri, ses bantları (**kaydedilir ve yazıya dökülür**), Meteor-M
uydu görüntüleri, ISS geçişleri ve öğrenen bir spektrum gözcüsü — tek RTL2832U üzerinde adil
zamanlanan 16 hedef.

> 🇬🇧 English README: [README.md](README.md) · Installation: [docs/INSTALL.md](docs/INSTALL.md)

- [Ne yapar](#ne-yapar)
- [Örnek mesajlar](#örnek-mesajlar)
- [Kurulum](#kurulum)
- [Yapılandırma](#yapılandırma)
- [Telegram komutları](#telegram-komutları)
- [Güvenlik modeli](#güvenlik-modeli)
- [Mimari](#mimari)
- [16 hedef ve arkasındaki araçlar](#16-hedef-ve-arkasındaki-araçlar)
- [Tek dongle zamanlaması](#tek-dongle-zamanlaması)
- [Saklama ve disk güvenliği](#saklama-ve-disk-güvenliği)
- [Sorun giderme](#sorun-giderme)
- [Lisans, bağış, yasal not](#lisans-bağış-yasal-not)

## Ne yapar

| | |
|---|---|
| 📡 **Tek dongle, 16 hedef** | Adil bir zamanlayıcı RTL-SDR'ı ADS-B, AIS, ACARS/VDL2, radyosonda, ISM sensörleri, APRS, 406/121.5 MHz acil vericiler, GSM hücre kimlikleri, dört ses bandı, Meteor-M, ISS, Inmarsat ve spektrum taraması arasında paylaştırır. FM radyo ve TV bantları kara listededir. |
| 💬 **Tek Telegram topic'i** | Her olay yapılandırılmış bir başlıkla (bant, tam frekans, yerel+UTC saat, süre, sinyal, konum, özet) ve kategori emojisiyle tek bir topic'e düşer. Acil olaylar kuyruğun önüne geçer ve sesli gelir. |
| 🎙️ **Kayıt + transkripsiyon** | Ses bantları squelch/VOX ile kaydedilir, Opus'a kodlanır ve faster-whisper ile yerelde yazıya dökülür (Türkçe, İngilizce, otomatik algılama). Ses ve metin birlikte gelir. |
| 🛰️ **Uydu geçişleri** | SatDump ile Meteor-M LRPT görüntüleri; ISS ses/SSTV/paket — TLE'den hesaplanan pencerelerde. |
| 🔭 **Spektrum gözcüsü** | 24–1766 MHz'in normal gürültü tabanını öğrenir; yeni güçlü sinyalleri şelale görüntüsüyle bildirir. |
| 🧰 **İşletim** | CSV ekli günlük özet, `/durum`, `/tara`, `/sustur`, `/oncelik` komutları, kalıcı çevrimdışı kuyruk, döngüsel saklama, disk koruması, log döndürme, systemd servisi. Varsayılan dil İngilizce, Türkçe yerleşik. |

## Örnek mesajlar

Botun ürettiği biçimle birebir (Türkçe dil seçiliyken).

### ADS-B — slot özeti

```
✈️ ADS-B Özet • Havacılık
├ Frekans aralığı   : 1090 MHz ADS-B
├ Yakalanan frekans : 1090.000 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : 1 dk 30 sn
├ Sinyal gücü       : -9.4 dBFS
├ Konum             : —
└ Özet              : 23 uçak görüldü (4 yeni), en yakın 6.8 km

Toplam 23 uçak (4 yeni), konumlu 19
Dinleme süresi: 90 sn

• THY1KA    38000 ft   6.8 km NE  🆕
• PGT4R     12300 ft  11.2 km E
• SXS88H     3100 ft  14.9 km SE
… ve 16 uçak daha
```

### ADS-B — yakın ve alçak uçak

```
✈️ ADS-B Uçak • Havacılık
├ Frekans aralığı   : 1090 MHz ADS-B
├ Yakalanan frekans : 1090.000 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : —
├ Sinyal gücü       : -11.2 dBFS
├ Konum             : 40.9600, 29.3500 (7.1 km KD)
└ Özet              : Yakın uçak THY1KA — 6.8 km

ICAO adresi: 4BA9C1
Çağrı kodu: THY1KA
İrtifa: 2900 ft  ⚠️ alçak uçuş
Yer hızı: 182 kt
Yön: 54° (NE)
Squawk: 4521
```

### Deniz VHF — ses kaydı + transkripsiyon (ses dosyası yanıt olarak eklenir)

```
🚢 Deniz VHF Ses • Denizcilik
├ Frekans aralığı   : 156.800 MHz · Kanal 16 (Acil/Çağrı)
├ Yakalanan frekans : 156.800 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : 14 sn
├ Sinyal gücü       : -18.3 dBFS (tepe)
├ Konum             : —
└ Özet              : Kıyı Emniyet, kıyı emniyet, burası Mavi Marmara, kanal altıya geçiyorum.

Kanal: Kanal 16 (Acil/Çağrı)
Tepe seviye: -18.3 dBFS  (ort. -24.1)

📝 Transkripsiyon (tr):
Kıyı Emniyet, kıyı emniyet, burası Mavi Marmara, kanal altıya geçiyorum.
```

### Acil — 406 MHz tehlike vericisi (öncelikli alarm)

```
🚨 ACİL 406 MHz • Acil Durum
├ Frekans aralığı   : 406 MHz / 121.5 MHz acil
├ Yakalanan frekans : 406.028 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : —
├ Sinyal gücü       : +21 dB taban üstü (tepe)
├ Konum             : —
└ Özet              : ⚠️ EPIRB/ELT/PLB acil durum vericisi (406 MHz) — 406.028 MHz

EPIRB/ELT/PLB acil durum vericisi (406 MHz)
406 MHz bandında güçlü patlama tespit edildi. Bu bant yalnızca EPIRB (gemi), ELT (uçak) ve PLB (kişisel) acil durum vericilerine ayrılmıştır. Gerçek bir acil durum olabilir — doğrulayın ve gerekirse yetkilileri arayın (AKUB/112).
```

### Spektrum — yeni sinyal (şelale görüntüsü ekli)

```
🔭 Spektrum Anomali • Genel Tarama
├ Frekans aralığı   : 240–440 MHz tarama
├ Yakalanan frekans : 433.075 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : —
├ Sinyal gücü       : +18 dB taban üstü
├ Konum             : —
└ Özet              : Yeni sinyal @ 433.075 MHz (+18 dB)

Tepe frekans: 433.075 MHz
Bant genişliği: ~75 kHz
Güç: -12.4 dB (+18 dB)
Gürültü tabanı: -30.6 dB
```

### Meteor-M — LRPT geçişi (görüntüler ekli)

```
🛰️ Meteor-M Görüntü • Uydu
├ Frekans aralığı   : 137 MHz Meteor-M LRPT
├ Yakalanan frekans : 137.100 MHz
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : 12 dk 22 sn
├ Sinyal gücü       : —
├ Konum             : —
└ Özet              : METEOR-M2 4 geçişi — 3 görüntü (maks 69°)

Uydu: METEOR-M2 4
Frekans: 137.100 MHz
Maks. irtifa: 69°
Görüntü: 3 adet
```

### ISM — yeni cihazlar (slot başına tek özet)

```
📡 ISM Yeni Cihazlar • ISM/Sensör
├ Frekans aralığı   : 433.92 / 868 MHz ISM
├ Yakalanan frekans : —
├ Zaman             : 2026-10-11 17:32:05 (+03:00) / 14:32:05 UTC
├ Süre              : —
├ Sinyal gücü       : —
├ Konum             : —
└ Özet              : Yeni cihaz: 5 öge

Bu slotta 11 farklı cihaz duyuldu.

• Hava istasyonu: Bresser-5in1 #112 (21.3 °C)
• Lastik (TPMS): Schrader #a3f1c2 (231 kPa)
• Sıcaklık/Nem sensörü: Nexus-TH #45 (18.9 °C)
• Kapı zili/Kumanda: Honeywell-ActivLink #7f3a
• Cihaz: Generic-Remote #0e11
```

Her sabah günlük özet (kategori başına olay sayıları, benzersiz uçak/gemi/sensör, öne çıkan
olaylar, toplam kayıt süresi, görüntü sayısı, yeni cihazlar, çalışma süresi, hatalar) CSV ile gelir.

## Kurulum

Her platform için adım adım, en baştan anlatan kılavuz: **[docs/INSTALL.tr.md](docs/INSTALL.tr.md)**
— Ubuntu/Debian · Raspberry Pi · Proxmox LXC (USB geçişi) · Windows.

Kısa yol (Linux):
```bash
git clone https://github.com/haliskilic/rtlsdr-telegram.git && cd rtlsdr-telegram
sudo bash install/debian-linux.sh                 # paketler, kaynak derlemeler, venv, systemd
python3 tools/telegram_ids.py <BOT_TOKEN>         # chat_id / thread_id / kullanıcı kimliğinizi bulur
sudo nano /opt/rtlsdr-telegram/config.yaml        # token, chat_id, thread_id, admins, lat/lon, language: tr
/opt/rtlsdr-telegram/venv/bin/python /opt/rtlsdr-telegram/run.py --check -c /opt/rtlsdr-telegram/config.yaml
sudo systemctl enable --now rtlsdr-telegram
```
Ayrıca bkz. [QUICKSTART.tr.md](QUICKSTART.tr.md).

## Yapılandırma

Tek dosya: `config.yaml` (açıklamalı örnekler: [config.example.tr.yaml](config.example.tr.yaml),
İngilizce [config.example.yaml](config.example.yaml)). Koda dokunmadan her şey ayarlanır: dil,
Telegram token/grup/topic/yöneticiler, hedef başına açık/kapalı, frekanslar, dinleme süresi,
periyot, eşikler, öncelik; transkripsiyon motoru ve dili; günlük özet saati; kara liste; istasyon
konumu; saklama süresi. En küçük `config.yaml`:

```yaml
language: tr
telegram:
  token: "123456789:AAF..."
  chat_id: -1001234567890
  thread_id: 123
  admins: [987654321]
station: {name: "İstasyonum", lat: 41.0082, lon: 28.9784}
```

## Telegram komutları

Mesaj dilinden bağımsız olarak hem Türkçe hem İngilizce komut adları çalışır.
Yalnızca yapılandırılmış yöneticilere yanıt verilir.

| Komut | İngilizce | Açıklama |
|-------|-----------|----------|
| `/durum` | `/status` | aktif hedefler, dinlenen bant, CPU/sıcaklık, uptime, sıradaki uydu geçişi |
| `/liste` | `/list` | tüm hedefler, durumları ve araç varlığı |
| `/tara 145.500 [sn] [am\|fm]` | `/scan` | frekansı hemen dinle; kayıt + transkript gönderilir |
| `/sustur <kategori>` | `/mute` | kategoriyi sustur (acil her zaman geçer) |
| `/ac <kategori>` | `/unmute` | susturmayı kaldır |
| `/oncelik <hedef>` | `/priority` | hedefi döngünün önüne al |
| `/ozet` | `/summary` | günlük özeti şimdi üret |
| `/kayitlar [n]` | `/recordings` | son n kaydı yeniden gönder |
| `/gecisler [saat]` | `/passes` | yaklaşan Meteor-M / ISS geçişleri |
| `/yardim` | `/help` | komut listesi |

## Güvenlik modeli

- Bot **yalnızca yapılandırılmış grup/topic'e** yazar.
- Komutlar **yalnızca `telegram.admins` listesindeki kullanıcı kimliklerinden** ve yalnızca
  yapılandırılmış grup içinden (ya da bir yöneticinin özel mesajından) kabul edilir. Boş yönetici
  listesi herkesi reddeder.
- Başka gruplardan gelen komutlar yok sayılır; **bot yabancı bir gruba eklenirse otomatik ayrılır**;
  özelden yazan yabancılar **yanıt almaz**.
- Token yalnızca `config.yaml`'da durur (`chmod 600`); loglara ve depoya girmez (hata metinleri
  temizlenir). Öneri: BotFather'da `/setjoingroups` → Disable.
- Bu kurallar birim testleriyle doğrulanır (`tests/test_security.py`).

## Mimari

```
            ┌───────────────────────────────────────────────┐
            │  Application (config, log, yaşam döngüsü)      │
            └──────────────┬────────────────────────────────┘
   ┌──────────┬────────────┼──────────────┬────────────────┐
┌──▼───┐  ┌───▼──────┐  ┌───▼─────────┐ ┌──▼────────┐ ┌─────▼──────┐
│ SDR  │  │Zamanlayıcı│ │ 16 Hedef    │ │Dispatcher │ │ Komutlar   │
│lease │◄─┤adil zaman├─►│ (her biri   ├─►│ kuyruk →  │ │ (yalnız    │
│probe │  │ dilimleme│  │  bir sınıf) │ │ Telegram  │ │ yönetici)  │
└──┬───┘  └──────────┘  └──┬──────┬───┘ └─────┬─────┘ └────────────┘
   │ rtl_fm / rtl_power     │      │           │
┌──▼──────────────┐   ┌─────▼──┐ ┌─▼─────────┐ ┌─▼──────────────────┐
│ harici araçlar  │   │Transkr.│ │Uydu       │ │ SQLite: olaylar,   │
│ readsb rtl_433  │   │işçisi  │ │tahmincisi │ │ kalıcı kuyruk,     │
│ AIS-catcher ... │   │whisper │ │(TLE)      │ │ defter, kayıtlar   │
└─────────────────┘   └────────┘ └───────────┘ └────────────────────┘
```
Her hedef `rtlsdr_telegram/targets/` altında bir modüldür, ortak bir `Event` üretir, harici
çözücüleri alt süreç olarak çalıştırıp çıktılarını ayrıştırır. Çöken bir hedef diğerlerini
etkilemez; dispatcher gönderilemeyen mesajları Telegram erişilene kadar SQLite'ta tutar.

## 16 hedef ve arkasındaki araçlar

| # | Hedef | Bant | Araç | Çıktı |
|---|-------|------|------|-------|
| 1 | Uçak ADS-B | 1090 MHz | readsb | slot özeti, yakın/alçak uyarıları, squawk 7500/7600/7700 alarmı |
| 2 | ACARS / VDL2 | 131 / 136.9 MHz | acarsdec, dumpvdl2 | metin mesajları |
| 3 | Gemi AIS | 161.975/162.025 MHz | AIS-catcher | slot özeti, yakın gemi uyarıları, AIS-SART alarmı |
| 4 | Radyosonda | 400–406 MHz | rtl_power (+ radiosonde_auto_rx) | taşıyıcı adayları; auto_rx ile kalkış/patlama/düşüş |
| 5 | ISM sensörler | 433.92 / 868 MHz | rtl_433 | yeni cihazlar (toplu) |
| 6 | APRS | 144.800 MHz | multimon-ng | konum, mesaj |
| 7 | Acil vericiler | 406 / 121.5 MHz | rtl_power / rtl_fm | **öncelikli alarm**, 121.5 kaydı |
| 8 | GSM envanteri | 900/1800 MHz | gr-gsm | yalnız hücre kimlikleri (içerik yok) |
| 9–12 | Ses: amatör, hava, deniz, CB/PMR | 144/430, 118–137, 156–162, 27/446 MHz | rtl_fm + VOX | kayıt + transkript |
| 13 | Meteor-M | 137 MHz LRPT | SatDump | geçiş başına görüntü |
| 14 | ISS | 145.800/145.825 MHz | rtl_fm / multimon-ng | ses, SSTV, paket |
| 15 | Inmarsat STD-C/AERO | ~1.5 GHz | SatDump / JAERO | metin (L-bant anten + LNA gerekir; varsayılan kapalı) |
| 16 | Spektrum gözcüsü | 24–1766 MHz | rtl_power | şelaleli anomaliler |

## Tek dongle zamanlaması

Hedeflerin sınıfı (`pass`: TLE'ye bağlı uydular, `waiting`: uzun dinleme isteyen çözücüler,
`opportunistic`: diğerleri), `dwell_s`, `period_s` ve `priority` değerleri vardır. Çakışmada
**acil > uydu geçişi > kullanıcı /oncelik > normal döngü**; normal döngü adildir:
`skor = (gecikme / periyot) / öncelik`, hiç çalışmamış hedef önce gelir. `/durum` neyin dinlendiğini
ve sıradakini gösterir.

## Saklama ve disk güvenliği

`paths.retention_days` / `retention_months` / `retention_years` döngüsel bir pencere tanımlar:
daha eski kayıtlar, olaylar, çalışmalar ve hatalar saatte bir silinir; cihaz defteri üç kat uzun
yaşar ki "yeni cihaz" uyarıları tekrarlanmasın. Araç logları 5 MB'ta, uygulama logu 5 MB × 5,
journal 200 MB ile sınırlıdır. Boş disk `min_free_disk_pct` altına inince en eski kayıtlar budanır,
kayıt duraklar ve günde bir uyarı gönderilir. SQLite aylık VACUUM edilir.

## Sorun giderme

[docs/INSTALL.tr.md](docs/INSTALL.tr.md#8-sorun-giderme) sonundaki tabloya bakın.

## Lisans, bağış, yasal not

Bu yazılım **kaynağı açık (source-available)** lisanslıdır (bkz. [LICENSE](LICENSE)): 30 gün serbestçe
değerlendirin; **herhangi bir miktar bağış yapan destekçiler kişisel ve ticari olmayan amaçlarla
süresiz, ücretsiz kullanıp değiştirebilir**; her türlü ticari kullanım yazardan lisans gerektirir.
Harici çözücüler kendi açık kaynak lisanslarını korur ([THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)).
İletişim / bağış / ticari lisans: **haliskilic90@gmail.com**.

Yazılım yalnızca alıcıdır. Ülkenizin radyo dinleme ve gizlilik yasalarına uymak sizin
sorumluluğunuzdadır. GSM hedefi yalnızca yayınlanan hücre kimliklerini okur, trafik çözmez.
Acil verici tespitleri en-iyi-çaba göstergeleridir, bir emniyet sistemi değildir — daima yetkili
makamları arayın.
