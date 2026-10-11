#!/usr/bin/env bash
# Ortak kurulum adımları (Linux/LXC/Raspberry Pi). root veya sudo ile çalıştırın.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/rtlsdr-telegram}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">>> Kurulum dizini: $INSTALL_DIR"
echo ">>> Kaynak: $SRC_DIR"

# 1) RTL-SDR kernel DVB sürücüsünü kara listeye al (dongle'ı librtlsdr kullansın)
echo ">>> DVB sürücüsü kara listeye alınıyor"
cat > /etc/modprobe.d/blacklist-rtlsdr.conf <<'BL'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist rtl2832_sdr
blacklist dvb_usb_v2
BL
for m in rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2; do rmmod "$m" 2>/dev/null || true; done

# 2) udev kuralı (dongle'a kök olmadan erişim)
echo ">>> udev kuralı yazılıyor"
cat > /etc/udev/rules.d/20-rtlsdr.rules <<'UD'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666", SYMLINK+="rtl_sdr"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"
UD
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

# 3) Kodu kur
echo ">>> Dosyalar kopyalanıyor"
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR"/rtlsdr_telegram "$SRC_DIR"/run.py "$SRC_DIR"/requirements.txt "$INSTALL_DIR"/
[ -f "$INSTALL_DIR/config.yaml" ] || cp "$SRC_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
chmod 600 "$INSTALL_DIR/config.yaml"   # bot token içerir
cp -r "$SRC_DIR"/tools "$INSTALL_DIR"/ 2>/dev/null || true

# 4) Python sanal ortamı (apt paketlerini de görsün)
echo ">>> Python sanal ortamı"
python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 5) systemd servisi
echo ">>> systemd servisi kuruluyor"
sed "s#/opt/rtlsdr-telegram#$INSTALL_DIR#g" "$SRC_DIR/rtlsdr-telegram.service" > /etc/systemd/system/rtlsdr-telegram.service
systemctl daemon-reload

echo ""
echo ">>> TAMAM. Sonraki adımlar:"
echo "    1) $INSTALL_DIR/config.yaml dosyasını düzenleyin (Telegram token, chat_id, admins)."
echo "    2) Test: $INSTALL_DIR/venv/bin/python $INSTALL_DIR/run.py --check -c $INSTALL_DIR/config.yaml"
echo "    3) Başlat: systemctl enable --now rtlsdr-telegram"
echo "    4) Günlük: journalctl -u rtlsdr-telegram -f"
