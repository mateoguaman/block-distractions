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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Block Distractions</title>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif;
            max-width: 100%;
            padding: 24px 20px;
            background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%);
            color: #fff;
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
        }
        .container { max-width: 380px; margin: 0 auto; }

        /* Status badge */
        .status-badge {
            text-align: center;
            padding: 32px 20px;
            margin-bottom: 24px;
        }
        .status-badge h1 {
            font-size: 14px;
            font-weight: 500;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 12px;
        }
        .status-main {
            font-size: 42px;
            font-weight: 700;
            letter-spacing: -1px;
        }
        .status-main.blocked { color: #ff6b6b; }
        .status-main.unlocked { color: #51cf66; }
        .status-sub {
            font-size: 15px;
            color: #888;
            margin-top: 8px;
        }

        /* Info card */
        .card {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .card-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
        }
        .card-row:not(:last-child) {
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .card-label { color: #888; font-size: 14px; }
        .card-value { font-weight: 600; font-size: 15px; }

        /* Conditions */
        .conditions-title {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }
        .condition {
            display: flex;
            align-items: flex-start;
            padding: 10px 0;
            font-size: 14px;
            color: #aaa;
        }
        .condition-icon {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 12px;
            flex-shrink: 0;
            font-size: 12px;
        }
        .condition-icon.met { background: rgba(81, 207, 102, 0.2); color: #51cf66; }
        .condition-icon.unmet { background: rgba(255, 107, 107, 0.2); color: #ff6b6b; }

        /* Buttons */
        .btn {
            display: block;
            width: 100%;
            padding: 18px;
            margin: 8px 0;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            -webkit-tap-highlight-color: transparent;
        }
        .btn:active { transform: scale(0.98); opacity: 0.9; }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-danger {
            background: transparent;
            color: #ff6b6b;
            border: 1px solid rgba(255, 107, 107, 0.3);
        }
        .btn-secondary {
            background: transparent;
            color: #666;
            font-weight: 500;
            font-size: 14px;
            padding: 14px;
        }
        .btn-secondary:active { background: rgba(255,255,255,0.03); }

        /* Toast message */
        .toast {
            position: fixed;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            background: #333;
            color: #fff;
            padding: 14px 24px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 500;
            opacity: 0;
            transition: all 0.3s ease;
            pointer-events: none;
            z-index: 100;
        }
        .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
        .toast.success { background: #51cf66; }
        .toast.error { background: #ff6b6b; }
        .toast.pending { background: #fcc419; color: #000; }

        /* Login */
        .login-box {
            padding: 40px 20px;
            text-align: center;
        }
        .login-box h2 {
            font-size: 24px;
            margin-bottom: 8px;
        }
        .login-box p {
            color: #666;
            font-size: 14px;
            margin-bottom: 24px;
        }
        .login-box input {
            width: 100%;
            padding: 16px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            background: rgba(255,255,255,0.03);
            color: #fff;
            font-size: 16px;
            margin-bottom: 12px;
            text-align: center;
        }
        .login-box input::placeholder { color: #444; }
        .login-box input:focus { outline: none; border-color: #667eea; }

        .hidden { display: none !important; }
        .updated { font-size: 11px; color: #444; text-align: center; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="login-box" id="login-box">
            <h2>Block Distractions</h2>
            <p>Enter your auth token to continue</p>
            <input type="password" id="token-input" placeholder="Auth token">
            <button class="btn btn-primary" onclick="saveToken()">Continue</button>
        </div>

        <div id="main-content" class="hidden">
            <div class="status-badge">
                <h1>Current Status</h1>
                <div class="status-main" id="status-value">--</div>
                <div class="status-sub" id="status-sub"></div>
            </div>

            <div class="card">
                <div class="card-row">
                    <span class="card-label">Emergency unlocks</span>
                    <span class="card-value" id="emergency-value">--</span>
                </div>
            </div>

            <div class="card" id="conditions-card">
                <div class="conditions-title">Conditions</div>
                <div id="conditions"></div>
            </div>

            <button class="btn btn-primary" id="btn-unlock" onclick="requestUnlock()">
                Check Conditions & Unlock
            </button>

            <button class="btn btn-danger" id="btn-emergency" onclick="requestEmergency()">
                Emergency Unlock
            </button>

            <button class="btn btn-secondary" onclick="loadStatus()">
                Refresh
            </button>

            <div class="updated" id="updated"></div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

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
                if (res.status === 401) {
                    localStorage.removeItem('block_auth_token');
                    AUTH_TOKEN = '';
                    checkAuth();
                    return;
                }
                const data = await res.json();

                const statusEl = document.getElementById('status-value');
                const subEl = document.getElementById('status-sub');

                if (data.blocked) {
                    statusEl.textContent = 'BLOCKED';
                    statusEl.className = 'status-main blocked';
                    subEl.textContent = 'Complete conditions to unlock';
                } else {
                    statusEl.textContent = 'UNLOCKED';
                    statusEl.className = 'status-main unlocked';
                    subEl.textContent = data.unlock_remaining ? data.unlock_remaining + ' remaining' : '';
                }

                document.getElementById('emergency-value').textContent =
                    (data.emergency_remaining !== undefined ? data.emergency_remaining : '3') + ' left today';

                // Render conditions
                const condEl = document.getElementById('conditions');
                if (data.conditions && data.conditions.length > 0) {
                    condEl.innerHTML = data.conditions.map(c => `
                        <div class="condition">
                            <span class="condition-icon ${c.met ? 'met' : 'unmet'}">
                                ${c.met ? '&#10003;' : '&#10007;'}
                            </span>
                            <span><strong>${c.name}</strong>: ${c.description}</span>
                        </div>
                    `).join('');
                } else {
                    document.getElementById('conditions-card').classList.add('hidden');
                }

                document.getElementById('updated').textContent =
                    'Updated ' + new Date().toLocaleTimeString();
            } catch (e) {
                console.error('Failed to load status:', e);
            }
        }

        function showToast(text, type) {
            const el = document.getElementById('toast');
            el.textContent = text;
            el.className = 'toast show ' + type;
            setTimeout(() => el.classList.remove('show'), 3000);
        }

        async function requestUnlock() {
            try {
                const res = await fetch('/unlock', { method: 'POST', headers: headers() });
                const data = await res.json();
                if (data.error) {
                    showToast(data.error, 'error');
                } else {
                    showToast('Request sent! Checking...', 'pending');
                    // Poll for completion
                    setTimeout(loadStatus, 5000);
                    setTimeout(loadStatus, 15000);
                    setTimeout(loadStatus, 30000);
                }
            } catch (e) {
                showToast('Request failed', 'error');
            }
        }

        async function requestEmergency() {
            if (!confirm('Use 1 of your emergency unlocks?')) return;
            try {
                const res = await fetch('/emergency', { method: 'POST', headers: headers() });
                const data = await res.json();
                if (data.error) {
                    showToast(data.error, 'error');
                } else {
                    showToast('Emergency request sent!', 'pending');
                    setTimeout(loadStatus, 5000);
                    setTimeout(loadStatus, 15000);
                    setTimeout(loadStatus, 30000);
                }
            } catch (e) {
                showToast('Request failed', 'error');
            }
        }

        checkAuth();
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
