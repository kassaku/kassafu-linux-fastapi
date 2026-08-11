#!/usr/bin/env bash
set -e

# ============================
# KassaFu Installer
# Installs to ~/zhongcan/
# System-level systemd service (starts at boot)
# Requires: sudo ./install.sh
# ============================

REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME="$(eval echo "~$REAL_USER")"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$REAL_HOME/zhongcan"

echo "Installing KassaFu to $INSTALL_DIR ..."

# --- Create directories ---
mkdir -p "$INSTALL_DIR/.restaurant"
mkdir -p "$INSTALL_DIR/venv"

# --- Copy project files ---
cp "$SCRIPT_DIR/kassafu.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/mypos_terminal.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/mypos_gateway.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/sumup_terminal.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/ccv.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/test_reader_status.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/test_real_payment.py" "$INSTALL_DIR/"

if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
fi

# --- Config ---
if [ -f "$SCRIPT_DIR/config.json" ]; then
    cp "$SCRIPT_DIR/config.json" "$INSTALL_DIR/.restaurant/"
    ln -sf .restaurant/config.json "$INSTALL_DIR/config.json"
    echo "  Config -> $INSTALL_DIR/.restaurant/config.json"
fi

if [ -f "$SCRIPT_DIR/.env.example" ]; then
    cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/"
fi

# --- Virtual environment ---
echo "  Creating virtual environment ..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    pip install -r "$INSTALL_DIR/requirements.txt"
fi

# --- Systemd system service ---
cat > /etc/systemd/system/kassafu.service << SERVICEEOF
[Unit]
Description=KassaFu Payment Bridge Service
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$REAL_USER
Group=$REAL_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/kassafu.py --server
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo "  Service -> /etc/systemd/system/kassafu.service"

systemctl daemon-reload
systemctl enable --now kassafu

echo ""
echo "KassaFu installed."
echo "  Status: systemctl status kassafu"
echo "  Logs:   journalctl -u kassafu -f"
echo "  Config: $INSTALL_DIR/.restaurant/config.json"
