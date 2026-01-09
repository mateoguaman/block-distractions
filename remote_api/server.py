"""Simple web server for phone-based unlock requests.

This runs on the Google Cloud VM and allows phone access to trigger unlocks.
The daemon on boss polls this server for pending requests.
"""

import json
import os
import time
import uuid
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# Configuration via environment variables
DATA_DIR = Path(os.environ.get("BLOCK_DATA_DIR", "/var/lib/block_distractions"))
AUTH_TOKEN = os.environ.get("BLOCK_AUTH_TOKEN", "")

REQUESTS_FILE = DATA_DIR / "requests.json"
STATUS_FILE = DATA_DIR / "status.json"


def require_auth(f):
    """Decorator to require auth token for sensitive endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_TOKEN:
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if token != AUTH_TOKEN:
                return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def load_requests() -> list[dict]:
    """Load pending requests from file."""
    if REQUESTS_FILE.exists():
        try:
            return json.loads(REQUESTS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_requests(requests: list[dict]) -> None:
    """Save requests to file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_FILE.write_text(json.dumps(requests, indent=2))


def load_status() -> dict:
    """Load current status from file."""
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_status(status: dict) -> None:
    """Save status to file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status, indent=2))


# Mobile-friendly HTML page
MOBILE_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Block Distractions</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 400px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }
        h1 { text-align: center; margin-bottom: 30px; }
        .status-box {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #0f3460;
        }
        .status-row:last-child { border-bottom: none; }
        .label { color: #888; }
        .value { font-weight: 600; }
        .blocked { color: #e74c3c; }
        .unlocked { color: #2ecc71; }
        .btn {
            display: block;
            width: 100%;
            padding: 16px;
            margin: 10px 0;
            border: none;
            border-radius: 12px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.1s, opacity 0.1s;
        }
        .btn:active { transform: scale(0.98); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-unlock {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-emergency {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }
        .btn-refresh {
            background: #16213e;
            color: #888;
            border: 1px solid #0f3460;
        }
        .message {
            text-align: center;
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            display: none;
        }
        .message.show { display: block; }
        .message.success { background: #2ecc71; color: white; }
        .message.error { background: #e74c3c; color: white; }
        .message.pending { background: #f39c12; color: white; }
        .pending-indicator {
            display: none;
            text-align: center;
            padding: 10px;
            color: #f39c12;
        }
        .pending-indicator.show { display: block; }
        .conditions {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #0f3460;
        }
        .condition {
            display: flex;
            align-items: center;
            padding: 6px 0;
        }
        .condition-icon { margin-right: 10px; font-size: 16px; }
        .condition-met { color: #2ecc71; }
        .condition-unmet { color: #e74c3c; }
        .login-box {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .login-box input {
            width: 100%;
            padding: 12px;
            border: 1px solid #0f3460;
            border-radius: 8px;
            background: #1a1a2e;
            color: #eee;
            font-size: 16px;
            margin-bottom: 10px;
        }
        .login-box input::placeholder { color: #666; }
        .hidden { display: none; }
    </style>
</head>
<body>
    <h1>Block Distractions</h1>

    <div class="login-box" id="login-box">
        <input type="password" id="token-input" placeholder="Enter auth token">
        <button class="btn btn-unlock" onclick="saveToken()">Save Token</button>
    </div>

    <div id="main-content" class="hidden">
        <div class="status-box" id="status-box">
            <div class="status-row">
                <span class="label">Status</span>
                <span class="value" id="status-value">Loading...</span>
            </div>
            <div class="status-row">
                <span class="label">Remaining</span>
                <span class="value" id="remaining-value">--</span>
            </div>
            <div class="status-row">
                <span class="label">Emergency</span>
                <span class="value" id="emergency-value">--</span>
            </div>
            <div class="conditions" id="conditions"></div>
        </div>

        <div class="message" id="message"></div>
        <div class="pending-indicator" id="pending">Request pending... waiting for daemon</div>

        <button class="btn btn-unlock" id="btn-unlock" onclick="requestUnlock()">
            Unlock (Check Conditions)
        </button>

        <button class="btn btn-emergency" id="btn-emergency" onclick="requestEmergency()">
            Emergency Unlock
        </button>

        <button class="btn btn-refresh" onclick="loadStatus()">
            Refresh Status
        </button>
    </div>

    <script>
        let AUTH_TOKEN = localStorage.getItem('block_auth_token') || '';

        function saveToken() {
            const token = document.getElementById('token-input').value.trim();
            if (token) {
                localStorage.setItem('block_auth_token', token);
                AUTH_TOKEN = token;
                checkAuth();
            }
        }

        function checkAuth() {
            if (AUTH_TOKEN) {
                document.getElementById('login-box').classList.add('hidden');
                document.getElementById('main-content').classList.remove('hidden');
                loadStatus();
            } else {
                document.getElementById('login-box').classList.remove('hidden');
                document.getElementById('main-content').classList.add('hidden');
            }
        }

        function headers() {
            const h = {'Content-Type': 'application/json'};
            if (AUTH_TOKEN) h['Authorization'] = 'Bearer ' + AUTH_TOKEN;
            return h;
        }

        async function loadStatus() {
            try {
                const res = await fetch('/status', {headers: headers()});
                const data = await res.json();

                const statusEl = document.getElementById('status-value');
                if (data.is_blocked) {
                    statusEl.textContent = 'BLOCKED';
                    statusEl.className = 'value blocked';
                } else {
                    statusEl.textContent = 'UNLOCKED';
                    statusEl.className = 'value unlocked';
                }

                document.getElementById('remaining-value').textContent =
                    data.unlock_remaining_formatted || '--';
                document.getElementById('emergency-value').textContent =
                    data.emergency_remaining + ' remaining';

                // Render conditions
                const condEl = document.getElementById('conditions');
                if (data.conditions && data.conditions.length > 0) {
                    condEl.innerHTML = data.conditions.map(c => `
                        <div class="condition">
                            <span class="condition-icon ${c.met ? 'condition-met' : 'condition-unmet'}">
                                ${c.met ? '&#10003;' : '&#10007;'}
                            </span>
                            <span>${c.name}: ${c.description}</span>
                        </div>
                    `).join('');
                }

                // Check for pending requests
                checkPending();
            } catch (e) {
                console.error('Failed to load status:', e);
            }
        }

        async function checkPending() {
            try {
                const res = await fetch('/pending', {headers: headers()});
                const data = await res.json();
                const pending = data.requests && data.requests.length > 0;
                document.getElementById('pending').classList.toggle('show', pending);
            } catch (e) {}
        }

        function showMessage(text, type) {
            const el = document.getElementById('message');
            el.textContent = text;
            el.className = 'message show ' + type;
            setTimeout(() => el.classList.remove('show'), 5000);
        }

        async function requestUnlock() {
            try {
                const res = await fetch('/unlock', {
                    method: 'POST',
                    headers: headers()
                });
                const data = await res.json();
                if (data.error) {
                    showMessage(data.error, 'error');
                } else {
                    showMessage('Unlock request queued!', 'pending');
                    document.getElementById('pending').classList.add('show');
                }
            } catch (e) {
                showMessage('Request failed', 'error');
            }
        }

        async function requestEmergency() {
            if (!confirm('Use an emergency unlock?')) return;
            try {
                const res = await fetch('/emergency', {
                    method: 'POST',
                    headers: headers()
                });
                const data = await res.json();
                if (data.error) {
                    showMessage(data.error, 'error');
                } else {
                    showMessage('Emergency unlock queued!', 'pending');
                    document.getElementById('pending').classList.add('show');
                }
            } catch (e) {
                showMessage('Request failed', 'error');
            }
        }

        // Check auth and load status on page load
        checkAuth();

        // Auto-refresh every 30 seconds
        setInterval(() => { if (AUTH_TOKEN) loadStatus(); }, 30000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Serve the mobile-friendly web page."""
    return render_template_string(MOBILE_PAGE)


@app.route("/status")
@require_auth
def get_status():
    """Get current blocking status."""
    status = load_status()
    return jsonify(status)


@app.route("/pending")
@require_auth
def get_pending():
    """Get pending unlock requests (for daemon polling)."""
    requests = load_requests()
    return jsonify({"requests": requests})


@app.route("/unlock", methods=["POST"])
@require_auth
def request_unlock():
    """Queue a proof-of-work unlock request."""
    requests = load_requests()

    # Check if there's already a pending unlock request
    for req in requests:
        if req["type"] == "unlock" and req["status"] == "pending":
            return jsonify({"message": "Unlock request already pending", "id": req["id"]})

    req_id = str(uuid.uuid4())[:8]
    requests.append({
        "id": req_id,
        "type": "unlock",
        "status": "pending",
        "created_at": time.time(),
    })
    save_requests(requests)

    return jsonify({"message": "Unlock request queued", "id": req_id})


@app.route("/emergency", methods=["POST"])
@require_auth
def request_emergency():
    """Queue an emergency unlock request."""
    requests = load_requests()

    # Check if there's already a pending emergency request
    for req in requests:
        if req["type"] == "emergency" and req["status"] == "pending":
            return jsonify({"message": "Emergency request already pending", "id": req["id"]})

    req_id = str(uuid.uuid4())[:8]
    requests.append({
        "id": req_id,
        "type": "emergency",
        "status": "pending",
        "created_at": time.time(),
    })
    save_requests(requests)

    return jsonify({"message": "Emergency unlock request queued", "id": req_id})


@app.route("/complete/<req_id>", methods=["POST"])
@require_auth
def complete_request(req_id: str):
    """Mark a request as completed (called by daemon)."""
    data = request.get_json() or {}
    result = data.get("result", {})

    requests = load_requests()
    updated = False

    for req in requests:
        if req["id"] == req_id:
            req["status"] = "completed"
            req["result"] = result
            req["completed_at"] = time.time()
            updated = True
            break

    if updated:
        save_requests(requests)
        # Clean up old completed requests (keep last 10)
        completed = [r for r in requests if r["status"] == "completed"]
        pending = [r for r in requests if r["status"] == "pending"]
        requests = pending + completed[-10:]
        save_requests(requests)
        return jsonify({"message": "Request marked complete"})

    return jsonify({"error": "Request not found"}), 404


@app.route("/update-status", methods=["POST"])
@require_auth
def update_status():
    """Update the cached status (called by daemon after each action)."""
    data = request.get_json() or {}
    save_status(data)
    return jsonify({"message": "Status updated"})


if __name__ == "__main__":
    # For development only
    app.run(host="0.0.0.0", port=8080, debug=True)
