#!/bin/bash
# Setup script for the phone API on Google Cloud VM
#
# This script should be run on the VM to set up the Flask server.
# Prerequisites: SSH access to the VM
#
# Usage:
#   1. Copy remote_api/ to the VM:
#      scp -r remote_api/ user@VM_IP:~/block_distractions/
#   2. SSH to VM and run:
#      cd ~/block_distractions/remote_api && sudo ./setup_vm.sh

set -e

echo "Setting up Block Distractions Phone API..."

# Create data directory
DATA_DIR="/var/lib/block_distractions"
sudo mkdir -p "$DATA_DIR"
sudo chown "$USER:$USER" "$DATA_DIR"

# Initialize empty files
echo "[]" > "$DATA_DIR/requests.json"
echo "{}" > "$DATA_DIR/status.json"

# Install Python dependencies
echo "Installing Python dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

# Create virtual environment
VENV_DIR="$HOME/block_distractions/venv"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install flask gunicorn

# Generate a random auth token if not provided
AUTH_TOKEN="${BLOCK_AUTH_TOKEN:-$(openssl rand -hex 16)}"
echo ""
echo "=============================================="
echo "AUTH TOKEN: $AUTH_TOKEN"
echo "=============================================="
echo ""
echo "Save this token! You'll need to:"
echo "1. Add it to your phone's localStorage:"
echo "   localStorage.setItem('block_auth_token', '$AUTH_TOKEN')"
echo "2. Or add it to config.secrets.yaml:"
echo "   phone_api:"
echo "     auth_token: $AUTH_TOKEN"
echo ""

# Create systemd service
SERVICE_FILE="/etc/systemd/system/block-phone-api.service"
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Block Distractions Phone API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/block_distractions/remote_api
Environment="BLOCK_DATA_DIR=$DATA_DIR"
Environment="BLOCK_AUTH_TOKEN=$AUTH_TOKEN"
ExecStart=$VENV_DIR/bin/gunicorn -b 0.0.0.0:8080 -w 2 server:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload and start service
sudo systemctl daemon-reload
sudo systemctl enable block-phone-api
sudo systemctl start block-phone-api

echo ""
echo "Service started! Check status with:"
echo "  sudo systemctl status block-phone-api"
echo ""
echo "The API is now available at:"
echo "  http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "If you have a firewall, allow port 8080:"
echo "  sudo ufw allow 8080/tcp"
echo ""
echo "For HTTPS, set up nginx as a reverse proxy with Let's Encrypt."
