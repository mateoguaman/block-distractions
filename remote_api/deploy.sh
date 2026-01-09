#!/bin/bash
# Deploy the phone API to the Google Cloud VM
#
# Usage: ./deploy.sh [user@host]
#
# Example:
#   ./deploy.sh mateo@34.127.22.131

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="${1:-}"

if [ -z "$REMOTE" ]; then
    echo "Usage: $0 user@host"
    echo "Example: $0 mateo@34.127.22.131"
    exit 1
fi

echo "Deploying to $REMOTE..."

# Create remote directory
ssh "$REMOTE" "mkdir -p ~/block_distractions/remote_api"

# Copy files
scp "$SCRIPT_DIR/server.py" "$REMOTE:~/block_distractions/remote_api/"
scp "$SCRIPT_DIR/requirements.txt" "$REMOTE:~/block_distractions/remote_api/"
scp "$SCRIPT_DIR/setup_vm.sh" "$REMOTE:~/block_distractions/remote_api/"

# Run setup
ssh "$REMOTE" "cd ~/block_distractions/remote_api && chmod +x setup_vm.sh && sudo ./setup_vm.sh"

echo ""
echo "Deployment complete!"
