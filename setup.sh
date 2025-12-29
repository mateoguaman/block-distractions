#!/bin/bash
# Block Distractions Setup Script
# ================================
# This script sets up the block command and background daemon.
# Supports macOS and Linux (Ubuntu).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCK_CMD="$SCRIPT_DIR/block"

echo "=== Block Distractions Setup ==="
echo

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is required but not installed."
    echo "Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "Found uv: $(uv --version)"

# Set up virtual environment and install dependencies
echo "Setting up Python environment..."
cd "$SCRIPT_DIR"
uv sync
echo "Dependencies installed."

# Make block script executable
chmod +x "$BLOCK_CMD"
echo "Made block script executable"

# Create wrapper script in /usr/local/bin
echo
echo "Creating wrapper script in /usr/local/bin..."
WRAPPER_SCRIPT=$(cat <<EOF
#!/bin/bash
cd "$SCRIPT_DIR" && uv run ./block "\$@"
EOF
)
echo "$WRAPPER_SCRIPT" | sudo tee /usr/local/bin/block > /dev/null
sudo chmod +x /usr/local/bin/block
echo "Created: /usr/local/bin/block (wrapper for uv run)"

# Detect OS and install appropriate service
OS=$(uname -s)
echo
echo "Detected OS: $OS"

# Set up passwordless sudo for hosts file modification
echo
echo "Setting up passwordless sudo for /etc/hosts..."
SUDOERS_FILE="/etc/sudoers.d/block-distractions"

if [ "$OS" = "Darwin" ]; then
    # macOS sudoers rules
    SUDOERS_CONTENT="# Block Distractions - passwordless sudo for hosts file
$USER ALL=(ALL) NOPASSWD: /bin/cp * /etc/hosts
$USER ALL=(ALL) NOPASSWD: /usr/bin/dscacheutil -flushcache
$USER ALL=(ALL) NOPASSWD: /usr/bin/killall -HUP mDNSResponder
"
elif [ "$OS" = "Linux" ]; then
    # Linux sudoers rules (include both resolvectl and systemd-resolve for compatibility)
    SUDOERS_CONTENT="# Block Distractions - passwordless sudo for hosts file
$USER ALL=(ALL) NOPASSWD: /bin/cp * /etc/hosts
$USER ALL=(ALL) NOPASSWD: /usr/bin/resolvectl flush-caches
$USER ALL=(ALL) NOPASSWD: /usr/bin/systemd-resolve --flush-caches
"
fi

# Create sudoers file with correct permissions
echo "$SUDOERS_CONTENT" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"

# Validate sudoers file
if sudo visudo -c -f "$SUDOERS_FILE" 2>/dev/null; then
    echo "Passwordless sudo configured: $SUDOERS_FILE"
else
    echo "Warning: sudoers file validation failed. Removing..."
    sudo rm -f "$SUDOERS_FILE"
    echo "You may need to enter your password for block/unlock commands."
fi

if [ "$OS" = "Darwin" ]; then
    # macOS - use launchd
    echo "Setting up launchd service for macOS..."

    PLIST_NAME="com.block.daemon.plist"
    PLIST_SRC="$SCRIPT_DIR/services/$PLIST_NAME"
    PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

    # Update plist with correct paths
    sed -e "s|{{SCRIPT_DIR}}|$SCRIPT_DIR|g" \
        -e "s|{{USER}}|$USER|g" \
        -e "s|{{HOME}}|$HOME|g" \
        "$PLIST_SRC" > "$PLIST_DEST"

    # Unload if already loaded
    launchctl bootout gui/$(id -u)/com.block.daemon 2>/dev/null || true

    # Load the service
    launchctl load "$PLIST_DEST"

    echo "Installed launchd service: $PLIST_DEST"
    echo "Service will start automatically on login."
    echo
    echo "To start now:  launchctl start com.block.daemon"
    echo "To stop:       launchctl stop com.block.daemon"
    echo "To uninstall:  launchctl unload $PLIST_DEST && rm $PLIST_DEST"

elif [ "$OS" = "Linux" ]; then
    # Linux - use systemd user service
    echo "Setting up systemd user service for Linux..."

    SERVICE_NAME="block-daemon.service"
    SERVICE_SRC="$SCRIPT_DIR/services/$SERVICE_NAME"
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_DEST="$SERVICE_DIR/$SERVICE_NAME"

    mkdir -p "$SERVICE_DIR"

    # Update service file with correct paths
    sed -e "s|{{SCRIPT_DIR}}|$SCRIPT_DIR|g" \
        "$SERVICE_SRC" > "$SERVICE_DEST"

    # Reload systemd
    systemctl --user daemon-reload

    # Enable and start service
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"

    echo "Installed systemd service: $SERVICE_DEST"
    echo "Service enabled and started."
    echo
    echo "To check status: systemctl --user status $SERVICE_NAME"
    echo "To stop:         systemctl --user stop $SERVICE_NAME"
    echo "To disable:      systemctl --user disable $SERVICE_NAME"

else
    echo "Unknown OS: $OS"
    echo "Daemon auto-start not configured. You can run 'block daemon' manually."
fi

# Initial blocking setup
echo
echo "=== Initial Setup ==="
echo "Enabling initial blocking..."
uv run ./block on

echo
echo "=== Setup Complete ==="
echo
echo "Usage:"
echo "  block status     - Show current status"
echo "  block unlock     - Unlock via proof-of-work"
echo "  block emergency  - Emergency unlock"
echo "  block list       - List blocked sites"
echo "  block add <site> - Add a site"
echo
echo "Edit config.yaml to customize your setup."
echo "Don't forget to update the Obsidian vault path!"
