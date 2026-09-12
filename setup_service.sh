#!/usr/bin/env bash
# setup_service.sh - Install dependencies and configure systemd service on Raspberry Pi

set -e

echo "========================================================"
echo " Encinitas Tide Calendar - Raspberry Pi Setup"
echo " Target: Seeed reTerminal E1004 (13.3\" Spectra 6 E-Paper)"
echo "========================================================"

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="tidecalendar"
USER_NAME="$(whoami)"

echo "[1/4] Updating package lists and installing Chromium..."
sudo apt-get update -y
sudo apt-get install -y chromium-browser chromium python3-pip python3-venv

echo "[2/4] Setting up Python virtual environment..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "[3/4] Creating systemd service file..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Encinitas Tide Calendar Server for reTerminal E1004
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/server.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "[4/4] Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}.service
sudo systemctl restart ${SERVICE_NAME}.service

echo ""
echo "========================================================"
echo " Setup Complete!"
echo " Service status: sudo systemctl status ${SERVICE_NAME}"
echo " Service logs:   sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo " reTerminal E1004 image URL:"
IP_ADDR=$(hostname -I | awk '{print $1}')
echo " http://${IP_ADDR}:8080/screen/encinitas-tide"
echo ""
echo " Browser preview URL:"
echo " http://${IP_ADDR}:8080/preview"
echo "========================================================"
