# rtlsdr-telegram

Tek bir **RTL2832U / R860 (R820T2)** dongle ile çevreyi sürekli tarayan, FM radyo
ve TV yayınlarını yok sayan, yakaladığı olayları bir **Telegram grubunun tek bir
topic'ine** zengin başlıklarla gönderen; uygun bantlarda **ses kaydı** alıp bu
kayıtları **otomatik yazıya döken** modüler bir izleme sistemi.

> **Yasal not:** Bu yazılım yalnızca **dinleme/alma** yapar; hiçbir bantta yayın
> yapmaz. Bazı yayınların dinlenmesi ve özellikle içeriğinin kaydı/üçüncü kişilerle
> paylaşımı ülkenize göre yasal kısıtlamalara tabidir. GSM hedefi **yalnızca baz
> istasyonu kimlik envanteri** yapar (Cell ID/LAC/MCC/MNC); hücresel **içerik çözmez**.
> Acil durum bantlarını (406/121.5 MHz) yalnızca dinler. Sorumluluk kullanıcıdadır.

---

## İçindekiler
- [Mimari](#mimari)
- [İzlenen 16 hedef](#izlenen-16-hedef)
- [Mesaj formatı](#mesaj-formatı)
- [Kurulum](#kurulum)
- [Yapılandırma](#yapılandırma)
- [Telegram komutları](#telegram-komutları)
- [Özellikler: transkripsiyon, günlük özet](#özellikler)
- [Tek dongle zamanlama mantığı](#tek-dongle-zamanlama-mantığı)
- [Sorun giderme](#sorun-giderme)

---

## Mimari

```
                    ┌─────────────────────────────────────────────┐
                    │                 Application                 │
                    │  (config, logging, yaşam döngüsü, bakım)    │
                    └───────────────┬─────────────────────────────┘
                                    │
   ┌────────────┬──────────────────┼───────────────┬───────────────┐
   │            │                  │               │               │
┌──▼───┐   ┌────▼─────┐      ┌──────▼──────┐   ┌─────▼─────┐   ┌─────▼──────┐
│ SDR  │   │Scheduler │      │ 16 x Target │   │Dispatcher │   │ Commands   │
│ Mgr  │◄──┤ (tek     │─────►│  (her hedef │──►│ (kuyruk → │   │ (/durum,   │
│(lease│   │  dongle  │ lease│  ayrı sınıf)│   │ Telegram) │   │  /tara...) │
│ +probe)   │  slot)   │      └──────┬──────┘   └─────┬─────┘   └────────────┘
└──┬───┘   └──────────┘             │ Event          │
   │ rtl_fm/rtl_power/rtl_sdr       │          ┌─────▼──────┐
   │                                │          │ Telegram   │
┌──▼──────────┐              ┌──────▼───────┐  │  Client    │
│ Harici      │              │Transcription │  └────────────┘
│ araçlar     │              │  Worker      │
│ (readsb,    │              │(faster-      │  ┌────────────┐
│ rtl_433,    │              │ whisper)     │  │ Storage    │
│ AIS-catcher,│              └──────────────┘  │ (SQLite:   │
│ acarsdec,   │                                │ olaylar,   │
│ dumpvdl2,   │   ┌─────────────┐              │ kuyruk,    │
│ grgsm,      │   │ Satellite   │              │ cihaz      │
│ SatDump,    │   │ Predictor   │              │ defteri,   │
│ multimon-ng)│   │ (skyfield   │              │ kayıtlar)  │
└─────────────┘   │  + TLE)     │              └────────────┘
                  └─────────────┘
```

**İlkeler**
- Her hedef ayrı bir modül/sınıftır (`rtlsdr_telegram/targets/`), ortak
  `Event` veri modelini üretir.
- Harici çözücüler **alt süreç** olarak çağrılır; çıktıları (JSON/CSV/satır)
  ayrıştırılır. Araç seçimleri aşağıda gerekçeleriyle listelenmiştir.
- **Sağlamlık:** bir hedef çökerse diğerleri etkilenmez; zamanlayıcı bir sonrakine
  geçer, hata loglanır (`logs/errors.log`). Ağ kesilince mesajlar SQLite kuyrukta
  tutulur, bağlantı gelince gönderilir.
- **Tek dongle** bir muteks (lease) ile paylaşılır; zamanlayıcı kime ne kadar
  süre vereceğine öncelik kurallarıyla karar verir.

### Neden bu araçlar?
| Hedef | Araç | Gerekçe |
|------|------|---------|
| ADS-B | **readsb** | dump1090 uyumlu JSON, düşük CPU, Debian deposunda |
| ACARS | **acarsdec** | yerleşik JSON çıktısı (`-o 4`), çoklu frekans |
| VDL2 | **dumpvdl2** | `decoded:json` çıktısı, RTL desteği |
| AIS | **AIS-catcher** | tek dongle ile iki kanal, yüksek yakalama, JSON |
| ISM | **rtl_433** | yüzlerce protokol (hava ist., TPMS, kapı zili), JSON |
| APRS | **multimon-ng** | hafif, borudan AFSK1200; aprslib ile ayrıştırma |
| GSM | **gr-gsm** (grgsm_scanner) | hücre kimliği taraması, içerik çözmeden |
| Meteor-M | **SatDump** | LRPT ardışık düzeni, otomatik ürün görüntüsü |
| Radyosonda | **radiosonde_auto_rx** | telemetri (opsiyonel) + yerleşik taşıyıcı tespiti |
| Ses bantları | **rtl_fm** + kendi VOX'umuz | net kayıt sınırları, format bağımsız |
| Spektrum | **rtl_power** | SoapySDR gerektirmez, CSV güç taraması |
| Transkripsiyon | **faster-whisper** | CPU'da hızlı, Türkçe+İngilizce, yerel |

---

## İzlenen 16 hedef

**Metin bildirimi üretenler**
1. **ADS-B uçak** (1090 MHz) — çağrı kodu, konum, irtifa, hız; alçak uçuş;
   acil squawk 7500/7600/7700 → öncelikli alarm.
2. **ACARS/VDL2** (~131 / 136.7–137 MHz) — uçak veri mesajları, kuyruk no, sefer, metin.
3. **AIS gemi** (161.975/162.025 MHz) — gemi adı, MMSI, tip, rota/hız, "yeni gemi".
4. **Radyosonda** (400–406 MHz) — taşıyıcı tespiti; auto_rx ile kalkış/irtifa/
   patlama/tahmini düşüş.
5. **ISM sensörler** (433.92/868 MHz) — hava istasyonu, sıcaklık/nem, kapı zili,
   TPMS; "yeni cihaz görüldü".
6. **APRS** (144.800 MHz) — konum ve kısa mesajlar.
7. **Acil durum vericileri** (406 / 121.5 MHz) — **ÖNCELİKLİ ALARM**, 121.5'te kayıt.
8. **GSM envanteri** (900/1800) — yalnız Cell ID/LAC/MCC/MNC; yeni/değişen hücre.

**Ses kaydı üretenler** (eşik aşılınca kaydeder, yayın bitince kapatır → yazıya döker)
9. **Amatör telsiz** (144–146 / 430–440 MHz, FM).
10. **Hava bandı** (118–137 MHz, AM) — kule/yaklaşma/ATIS.
11. **Deniz VHF** (156–162 MHz, FM) — özellikle **Kanal 16**.
12. **CB / PMR446** (26–28 / 446 MHz, FM).

**Uydu / görüntü**
13. **Meteor-M** (LRPT, 137 MHz) — her geçişte görüntü (SatDump).
14. **ISS** (145.800/145.825 MHz) — geçişte ses, SSTV, veri paketi.
15. **Inmarsat** (~1.5 GHz STD-C/AERO) — **ek L-bant anten+LNA gerektirir**;
    aktif/pasif seçeneği, donanım yoksa otomatik atlar.

**Genel gözcü**
16. **Spektrum taraması** (24–1766 MHz, FM/TV hariç) — taban profili öğrenir;
    yeni/güçlü sinyalde frekans, süre, güç ve **şelale görüntüsü** gönderir.

---

## Mesaj formatı

Tüm olaylar **aynı topic'e** gider; ayırt etme başlıktaki yapılandırılmış alanlarla
ve kategori emojisiyle yapılır:

```
✈️ ADS-B Uçak • Havacılık
├ Frekans aralığı : 1090 MHz ADS-B
├ Yakalanan frekans: 1090.000 MHz
├ Zaman           : 2026-10-11 17:45:12 (+03:00) / 14:45:12 UTC
├ Süre            : —
├ Sinyal gücü     : -18.3 dBFS
├ Konum           : 41.1234, 29.0456 (12.4 km KD)
└ Özet            : Yeni uçak THY1KA — 12 km

ICAO adresi: 4BA9C1
Çağrı kodu : THY1KA
İrtifa     : 11800 ft
Yer hızı   : 420 kt
...
```

Ses olaylarında ses dosyası (.ogg) ve transkripsiyon aynı mesaj dizisinde gelir.
Uydu olaylarında .png görüntüler eklenir. Acil olaylar kuyruğun önüne geçer ve
sesli bildirim olarak gider.

Kategoriler: Havacılık ✈️, Denizcilik 🚢, Uydu 🛰️, Meteoroloji 🎈, Amatör Telsiz 📻,
ISM/Sensör 📡, Acil Durum 🚨, Hücresel 📶, Genel Tarama 🔭.

---

## Kurulum

### Proxmox LXC (bu depo bununla kuruldu)
Ayrıntılar için [`docs/PROXMOX.md`](docs/PROXMOX.md). Özet: ayrıcalıksız (unprivileged)
bir Debian 13 LXC oluşturulur, USB geçişi (cgroup `c 189:*` + `/dev/bus/usb` bind)
verilir, host'ta DVB sürücüsü kara listeye alınır.

### Linux PC / LXC
```bash
sudo bash install/debian-linux.sh
sudo nano /opt/rtlsdr-telegram/config.yaml   # token, chat_id, admins
/opt/rtlsdr-telegram/venv/bin/python /opt/rtlsdr-telegram/run.py --check -c /opt/rtlsdr-telegram/config.yaml
sudo systemctl enable --now rtlsdr-telegram
journalctl -u rtlsdr-telegram -f
```

### Raspberry Pi
```bash
sudo bash install/raspberrypi.sh
```
Pi'de `transcription.model: tiny` ve daha uzun `spectrum.period_s` önerilir.

### Windows
[`install/windows.md`](install/windows.md) adımlarını izleyin (Zadig sürücüsü +
hazır ikili araçlar + venv).

---

## Yapılandırma

Tek dosya: `config.yaml` (örnek: `config.example.yaml`). Koddan ayrı olarak
ayarlanabilenler: Telegram token/grup/topic/yöneticiler; her hedef için
aktif/pasif, frekans, dinleme süresi, eşik/squelch, öncelik; transkripsiyon
motoru ve dili; günlük özet saati; kara liste (FM/TV dahil); istasyon konumu
(uydu hesapları için); platform.

Kontrol komutu:
```bash
python run.py --check -c config.yaml        # yapılandırma + araç + dongle durumu
python run.py --test-telegram -c config.yaml # Telegram bağlantı testi
```

---

## Telegram komutları

Yalnızca `telegram.admins` listesindeki kullanıcılar çalıştırabilir.

| Komut | Açıklama |
|-------|----------|
| `/durum` | aktif hedefler, dinlenen bant, CPU/sıcaklık, uptime |
| `/liste` | tüm hedefler ve durumları |
| `/tara 145.500 [sn] [am\|fm]` | frekansı geçici dinle |
| `/sustur <kategori>` | kategoriyi geçici sustur |
| `/ac <kategori>` | kategoriyi geri aç |
| `/oncelik <hedef>` | hedefi tarama döngüsünde öne al |
| `/ozet` | günlük özeti hemen üret |
| `/kayitlar <n>` | son n ses kaydını yeniden gönder |
| `/yardim` | komut listesi |

---

## Özellikler

### A) Otomatik transkripsiyon
Her ses kaydı kapandıktan sonra otomatik yazıya dökülür. Motor seçilebilir
(`faster_whisper` varsayılan, `whisper`, `api`, `none`). Dil otomatik algılanır
(`auto`) veya hedefe göre zorlanır (havacılık için `en`, deniz/amatör için `tr`).
Transkripsiyon, dongle'ı meşgul etmeden ayrı iş parçacığında yapılır ve ilgili
ses dosyasıyla aynı mesaj dizisine eklenir. Başarısızsa "ses alındı, metin
çıkarılamadı" notuyla ham kayıt yine gönderilir.

### B) Günlük özet
Her gün `summary.time` saatinde: kategori sayıları, en aktif türler, benzersiz
uçak/gemi/sensör, en dikkat çeken 5 olay, toplam ses süresi, görüntü sayısı,
yeni cihaz/hücre/anomali, uptime ve hata özeti. İsteğe bağlı CSV eki.

---

## Tek dongle zamanlama mantığı

Hedefler iki sınıftır: **bekleme gerektirenler** (uydu/ISS geçişleri — TLE'den
hesaplanan pencerede önceliklidir) ve **fırsatçı taranlar** (ses bantları, ISM,
spektrum, ADS-B...). Çakışmada öncelik:

```
Acil Durum  >  zamanlanmış uydu geçişi  >  kullanıcı /oncelik  >  normal döngü
```

Her hedefe `dwell_s` (dinleme süresi) ve `period_s` (periyot) atanır. Döngü durumu
`/durum` ile görünür: "şu an X dinleniyor, sıradaki Y". Dongle yoksa döngü bekler
ve bunu bildirir; dongle takılınca otomatik devam eder.

---

## Sorun giderme

- **"Dongle bulunamadı"**: Host'ta/konteynerde `rtl_test` çalıştırın. Çıkmıyorsa
  dongle takılı değil ya da kernel DVB sürücüsü sahiplenmiş olabilir
  (`install/common.sh` kara listeyi uygular; `rmmod dvb_usb_rtl28xxu`).
- **LXC'de araç bulunamıyor**: Kaynaktan derlenenler `/usr/local/bin`'dedir;
  systemd servisi `PATH`'e bunu ekler. Elle çalıştırırken `PATH=/usr/local/bin:$PATH`.
- **Telegram mesajı gelmiyor**: `run.py --test-telegram`. Bot gruba eklenmiş ve
  topic kimliği doğru mu? Süpergrup kimliği `-100...` ile başlar.
- **Transkripsiyon boş/yavaş**: Model ilk çalışmada indirilir (internet gerekir).
  CPU'da `base`/`tiny` kullanın. `engine: none` ile kapatılabilir.
- **CPU yüksek**: `spectrum.period_s` artırın, `dwell_s` düşürün, gerekmeyen
  hedefleri `enabled: false` yapın.
- **Yetkisiz komut**: `telegram.admins` listesine kendi kullanıcı kimliğinizi
  ekleyin (`/durum` yetkisiz denemede kimliğinizi yazar; @userinfobot da verir).
- **Loglar**: `logs/rtlsdr-telegram.log` ve `logs/errors.log`; her araç için
  `logs/<araç>.log`.

---

## Lisans
MIT. Üçüncü taraf araçlar kendi lisanslarına tabidir.
