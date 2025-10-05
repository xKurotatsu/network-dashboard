from flask import Flask, render_template_string, jsonify
from routeros_api import RouterOsApiPool
import datetime, time
from collections import deque

app = Flask(__name__)

# === Mikrotik Settings ===
MIKROTIK_HOST = "10.10.0.1"
MIKROTIK_USER = "project"
MIKROTIK_PASS = "project123"
API_PORT = 8728
INTERFACE = "ether1-ISP"

# --- state for traffic computation & autoscale ---
_prev_rx = None
_prev_tx = None
_prev_time = None
PEAK_WINDOW = 12
peaks = deque(maxlen=PEAK_WINDOW)
DEFAULT_MAX_SPEED = 10.0

# === HTML Template with Hotspot Users Modal & fallback values ===
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Network Core Monitor</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
<style>
body { background: #f0f2f5; font-family: 'Segoe UI', sans-serif; color: #333; padding: 20px; }
.card { border: none; border-radius: 15px; box-shadow: 0 8px 20px rgba(0,0,0,0.08); transition: transform 0.3s, box-shadow 0.3s; }
.card:hover { transform: translateY(-6px); box-shadow: 0 12px 28px rgba(0,0,0,0.12); }
.metrics { display:flex; flex-wrap:wrap; gap:16px; justify-content:center; }
.metric { flex: 1 1 140px; max-width: 220px; cursor:pointer; }
.progress { height: 22px; border-radius: 11px; background: #e3e6ea; overflow: hidden; }
.progress-bar { transition: width 1s ease-in-out, box-shadow 0.6s; }
.download-bar { background: linear-gradient(90deg, #0d6efd, #6ea8fe); box-shadow: 0 6px 18px rgba(13,110,253,0.18); }
.upload-bar { background: linear-gradient(90deg, #ffc107, #ffd580); box-shadow: 0 6px 18px rgba(255,193,7,0.18); }
.label-small { font-size: 0.85rem; color: #555; }
.header { text-align:center; margin-bottom:30px; }
.header h3 { font-weight:600; font-size:1.5rem; }
.header p { color:#777; font-size:.9rem; }
.footer { text-align:center; margin-top:20px; font-size:.8rem; color:#666; }
.table-responsive { overflow-x:auto; }
</style>
</head>
<body>

<div class="container-fluid">
    <div class="header">
        <h3><i class="fas fa-wifi"></i> My Network Core Monitoring</h3>
        <p>Interface: <b>{{ iface }}</b> • Auto-scaling bars</p>
    </div>

    <!-- Metrics -->
    <div class="row metrics text-center">
        <div class="col-6 col-sm-6 col-md-3 metric">
            <div class="card p-3">
                <div class="label-small"><i class="fas fa-microchip"></i> CPU</div>
                <h4 id="cpu">--%</h4>
            </div>
        </div>
        <div class="col-6 col-sm-6 col-md-3 metric">
            <div class="card p-3">
                <div class="label-small"><i class="fas fa-memory"></i> Memory</div>
                <h4 id="mem">--%</h4>
            </div>
        </div>
        <div class="col-6 col-sm-6 col-md-3 metric">
            <div class="card p-3">
                <div class="label-small"><i class="fas fa-clock"></i> Uptime</div>
                <h4 id="uptime">--</h4>
            </div>
        </div>
        <div class="col-6 col-sm-6 col-md-3 metric" id="users-card" data-bs-toggle="modal" data-bs-target="#usersModal">
            <div class="card p-3">
                <div class="label-small"><i class="fas fa-user-friends"></i> Hotspot Users</div>
                <h4 id="users">--</h4>
            </div>
        </div>
    </div>

    <!-- Download/Upload -->
    <div class="row gy-4 mt-4">
        <div class="col-12 col-md-6">
            <div class="card p-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="label-small"><i class="fas fa-download"></i> Download</div>
                    <div id="download-val">-- Mbps</div>
                </div>
                <div class="progress mt-2">
                    <div id="down-bar" class="progress-bar download-bar" role="progressbar" style="width:0%"></div>
                </div>
                <div class="label-small mt-2">Scale: <span id="scale-download">-- Mbps</span></div>
            </div>
        </div>

        <div class="col-12 col-md-6">
            <div class="card p-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="label-small"><i class="fas fa-upload"></i> Upload</div>
                    <div id="upload-val">-- Mbps</div>
                </div>
                <div class="progress mt-2">
                    <div id="up-bar" class="progress-bar upload-bar" role="progressbar" style="width:0%"></div>
                </div>
                <div class="label-small mt-2">Scale: <span id="scale-upload">-- Mbps</span></div>
            </div>
        </div>
    </div>

    <div class="footer">
        Updated every <b>5s</b> • Auto-scale (link speed if available, else observed peaks)
    </div>
</div>

<!-- Hotspot Users Modal -->
<div class="modal fade" id="usersModal" tabindex="-1" aria-labelledby="usersModalLabel" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="usersModalLabel">Active Hotspot Users</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body table-responsive">
        <table class="table table-striped table-hover">
          <thead>
            <tr>
              <th>User</th>
              <th>IP Address</th>
              <th>Uptime</th>
              <th>MAC Address</th>
            </tr>
          </thead>
          <tbody id="users-list">
            <tr><td colspan="4" class="text-center">Loading...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function updateUI() {
    try {
        const r = await fetch('/data');
        const d = await r.json();

        document.getElementById('cpu').textContent = d.cpu + '%';
        document.getElementById('mem').textContent = d.memory + '%';
        document.getElementById('uptime').textContent = d.uptime;
        document.getElementById('users').textContent = d.active_users;

        const download = +d.download;
        const upload = +d.upload;
        const max_speed = +d.max_speed;

        document.getElementById('download-val').textContent = download.toFixed(2) + ' Mbps';
        document.getElementById('upload-val').textContent = upload.toFixed(2) + ' Mbps';
        document.getElementById('scale-download').textContent = Math.round(max_speed) + ' Mbps';
        document.getElementById('scale-upload').textContent = Math.round(max_speed) + ' Mbps';

        const downPct = Math.min((download / (max_speed || 1)) * 100, 100);
        const upPct = Math.min((upload / (max_speed || 1)) * 100, 100);

        document.getElementById('down-bar').style.width = downPct + '%';
        document.getElementById('up-bar').style.width = upPct + '%';

        document.getElementById('down-bar').style.boxShadow = `0 6px 20px rgba(13,110,253,${Math.min(downPct/100,0.6)})`;
        document.getElementById('up-bar').style.boxShadow = `0 6px 20px rgba(255,193,7,${Math.min(upPct/100,0.6)})`;
    } catch(err) { console.error(err); }
}
setInterval(updateUI, 5000);
updateUI();

// Load hotspot users when modal is shown
async function loadHotspotUsers() {
    try {
        const r = await fetch('/hotspot_users');
        const data = await r.json();
        const tbody = document.getElementById('users-list');
        tbody.innerHTML = '';

        if (data.users && data.users.length > 0) {
            data.users.forEach(u => {
                const tr = document.createElement('tr');

                const tdName = document.createElement('td');
                tdName.textContent = u.name || '-';
                tr.appendChild(tdName);

                const tdIP = document.createElement('td');
                tdIP.textContent = u.address || '-';
                tr.appendChild(tdIP);

                const tdUptime = document.createElement('td');
                tdUptime.textContent = u.uptime || '-';
                tr.appendChild(tdUptime);

                const tdMAC = document.createElement('td');
                tdMAC.textContent = u.mac || '-';
                tr.appendChild(tdMAC);

                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">No active users</td></tr>';
        }
    } catch (err) {
        console.error(err);
        document.getElementById('users-list').innerHTML = '<tr><td colspan="4" class="text-center text-danger">Error loading users</td></tr>';
    }
}


document.getElementById('users-card').addEventListener('click', loadHotspotUsers);
</script>
</body>
</html>
"""

# === Helper functions ===
def get_interface_bytes(api, iface_name):
    try:
        interfaces = api.get_resource('/interface').get(name=iface_name)
        if interfaces:
            info = interfaces[0]
            rx = int(info.get('rx-byte',0))
            tx = int(info.get('tx-byte',0))
            return rx, tx, info
    except: pass
    return None, None, None

def compute_speeds(rx_now, tx_now, now_ts):
    global _prev_rx, _prev_tx, _prev_time, peaks
    if _prev_rx is None or _prev_tx is None or _prev_time is None:
        _prev_rx, _prev_tx, _prev_time = rx_now, tx_now, now_ts
        return 0.0, 0.0
    elapsed = max(now_ts - _prev_time, 1.0)
    delta_rx = max(rx_now - _prev_rx,0)
    delta_tx = max(tx_now - _prev_tx,0)
    rx_mbps = (delta_rx*8)/elapsed/1_000_000.0
    tx_mbps = (delta_tx*8)/elapsed/1_000_000.0
    _prev_rx, _prev_tx, _prev_time = rx_now, tx_now, now_ts
    peaks.append(max(rx_mbps, tx_mbps))
    return rx_mbps, tx_mbps

def determine_max_speed(iface_info, observed_peaks):
    if iface_info:
        for k in ['link-speed','actual-link-speed','speed','link-speed-mbps','max-speed']:
            v = iface_info.get(k)
            if v:
                try:
                    digits = ''.join(ch for ch in str(v) if (ch.isdigit() or ch=='.'))
                    if digits:
                        num = float(digits)
                        if num > 1_000_000: num/=1_000_000
                        return num
                except: pass
    if observed_peaks:
        return max(max(observed_peaks)*1.2, DEFAULT_MAX_SPEED)
    return DEFAULT_MAX_SPEED

def get_data():
    global peaks
    try:
        api_pool = RouterOsApiPool(MIKROTIK_HOST, username=MIKROTIK_USER, password=MIKROTIK_PASS, port=API_PORT, plaintext_login=True)
        api = api_pool.get_api()
        res = api.get_resource('/system/resource').get()[0]
        cpu = int(res.get('cpu-load',0))
        mem_free = int(res.get('free-memory',0))
        mem_total = int(res.get('total-memory',1))
        memory = 100 - int((mem_free/mem_total)*100)
        uptime = res.get('uptime','0s')
        try:
            users = api.get_resource('/ip/hotspot/active').get()
            active_users = len(users)
        except:
            active_users = 0
        rx_now, tx_now, iface_info = get_interface_bytes(api, INTERFACE)
        now_ts = time.time()
        download_mbps, upload_mbps = compute_speeds(rx_now or 0, tx_now or 0, now_ts)
        current_max = determine_max_speed(iface_info, list(peaks))
        api_pool.disconnect()
        return {
            "cpu": cpu,
            "memory": memory,
            "uptime": uptime,
            "active_users": active_users,
            "download": max(download_mbps,0.0),
            "upload": max(upload_mbps,0.0),
            "max_speed": float(current_max)
        }
    except:
        return {
            "cpu":0,"memory":0,"uptime":"N/A","active_users":0,
            "download":0.0,"upload":0.0,"max_speed":float(max(max(peaks)*1.2 if peaks else DEFAULT_MAX_SPEED, DEFAULT_MAX_SPEED))
        }

def get_hotspot_users():
    try:
        api_pool = RouterOsApiPool(MIKROTIK_HOST, username=MIKROTIK_USER, password=MIKROTIK_PASS, port=API_PORT, plaintext_login=True)
        api = api_pool.get_api()
        users = api.get_resource('/ip/hotspot/active').get()
        result = []
        for u in users:
            result.append({
                "name": u.get('user','-'),
                "address": u.get('address','-'),
                "uptime": u.get('uptime','-'),
                "mac": u.get('mac-address','-')
            })
        api_pool.disconnect()
        return result
    except:
        return []


# === Flask routes ===
@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE, iface=INTERFACE)
@app.route('/data')
def data(): return jsonify(get_data())
@app.route('/hotspot_users')
def hotspot_users(): return jsonify({"users": get_hotspot_users()})

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Network Core Monitor running on port {port}")
    app.run(host='0.0.0.0', port=port)
