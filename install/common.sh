#!/usr/bin/env bash
# Common installation steps (Linux/LXC/Raspberry Pi). Run as root or with sudo.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/rtlsdr-telegram}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">>> Install dir: $INSTALL_DIR"
echo ">>> Source: $SRC_DIR"

# 1) Blacklist the kernel DVB driver so librtlsdr can use the dongle
echo ">>> Blacklisting the DVB kernel driver"
cat > /etc/modprobe.d/blacklist-rtlsdr.conf <<'BL'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist rtl2832_sdr
blacklist dvb_usb_v2
BL
for m in rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2; do rmmod "$m" 2>/dev/null || true; done

# 2) udev rule (access without root)
echo ">>> Writing udev rule"
cat > /etc/udev/rules.d/20-rtlsdr.rules <<'UD'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666", SYMLINK+="rtl_sdr"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"
UD
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

# 3) Install the code
echo ">>> Copying files"
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR"/rtlsdr_telegram "$SRC_DIR"/run.py "$SRC_DIR"/requirements.txt "$INSTALL_DIR"/
[ -f "$INSTALL_DIR/config.yaml" ] || cp "$SRC_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
chmod 600 "$INSTALL_DIR/config.yaml"   # contains the bot token
cp -r "$SRC_DIR"/tools "$INSTALL_DIR"/ 2>/dev/null || true

# 4) Python virtual environment (sees apt packages too)
echo ">>> Python virtual environment"
python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 4b) journald cap (service logs go to the journal; keep it bounded)
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/rtlsdr-telegram.conf <<'JD'
[Journal]
SystemMaxUse=200M
MaxRetentionSec=1month
JD
systemctl restart systemd-journald 2>/dev/null || true

# 5) systemd service
echo ">>> Installing systemd service"
sed "s#/opt/rtlsdr-telegram#$INSTALL_DIR#g" "$SRC_DIR/rtlsdr-telegram.service" > /etc/systemd/system/rtlsdr-telegram.service
systemctl daemon-reload

echo ""
echo ">>> DONE. Next steps:"
echo "    1) Edit $INSTALL_DIR/config.yaml (Telegram token, chat_id, thread_id, admins, lat/lon)."
echo "    2) Test: $INSTALL_DIR/venv/bin/python $INSTALL_DIR/run.py --check -c $INSTALL_DIR/config.yaml"
echo "    3) Start: systemctl enable --now rtlsdr-telegram"
echo "    4) Logs: journalctl -u rtlsdr-telegram -f"
