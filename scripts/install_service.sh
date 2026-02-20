#!/bin/bash
# install_service.sh - Install VRAM Guard as a systemd service

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root (sudo ./install_service.sh)"
  exit 1
fi

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$DIR/.."
SERVICE_FILE="/etc/systemd/system/vram_guard.service"
USER_NAME=$(logname || echo $SUDO_USER || whoami)

echo "Creating VRAM Guard systemd service..."

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=VRAM Guard - NVIDIA Memory Protection Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$ROOT_DIR
ExecStart=$ROOT_DIR/scripts/run_guard.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling VRAM Guard service to start on boot..."
systemctl enable vram_guard.service

echo "Starting VRAM Guard service..."
systemctl start vram_guard.service

echo "Installation complete! VRAM Guard is now running in the background."
echo "You can check its status with: systemctl status vram_guard"
echo "You can view logs with: journalctl -u vram_guard -f"
