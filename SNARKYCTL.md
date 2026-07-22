# Snarkypuss Control Panel

## Project Goal

Turn the `snarkypuss` VPS into a remotely controlled network appliance with a small private API and web dashboard.

The management interface will be reachable only through the WireGuard tunnel:

```text
Windows browser
      ↓ HTTPS over WireGuard
10.8.0.1 management service
      ↓
NordVPN CLI and selected system services
```

The initial system should support:

- Displaying NordVPN connection status.
- Connecting NordVPN to a configured server or location.
- Disconnecting NordVPN.
- Displaying the current public exit IP.
- Displaying WireGuard status.
- Displaying DNS service status.
- Restarting `dnsmasq`.
- Displaying basic VPS health information.

---

## Design Principles

1. **Private by default**

   The control service must listen only on the WireGuard address:

   ```text
   10.8.0.1
   ```

   It must never listen on the public interface or on `0.0.0.0`.

2. **No arbitrary shell execution**

   The API must expose a fixed set of operations. User-supplied text must never be interpolated into shell commands.

3. **Least privilege**

   The web application must not run as `root`. A dedicated service account should receive permission to execute only approved wrapper commands.

4. **Read-only first**

   Begin by exposing status information. Add state-changing actions only after command execution and parsing are reliable.

5. **Fail visibly**

   The dashboard should clearly report errors such as:

   - NordVPN daemon unavailable.
   - Server connection failure.
   - WireGuard unavailable.
   - DNS service failure.
   - Public-IP lookup timeout.

6. **Control plane independence**

   The dashboard must remain reachable over `wg0` while NordVPN connects, disconnects, or changes exit servers.

---

## Recommended Technology Stack

Use:

- Python 3
- FastAPI
- Uvicorn
- Plain HTML
- Plain CSS
- Minimal JavaScript
- Jinja2 templates
- YAML or JSON configuration
- `systemd`

Avoid adding a database initially. Server aliases and other settings can be stored in a small configuration file.

---

## Suggested Directory Layout

```text
/opt/snarkypuss-control/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── commands.py
│   ├── models.py
│   ├── security.py
│   ├── config.py
│   ├── static/
│   │   ├── dashboard.js
│   │   └── style.css
│   └── templates/
│       └── index.html
├── config/
│   └── servers.yaml
├── scripts/
│   ├── nordvpn-connect
│   ├── nordvpn-disconnect
│   ├── dnsmasq-restart
│   └── public-ip
├── tests/
│   ├── test_commands.py
│   ├── test_api.py
│   └── fixtures/
│       ├── nordvpn-connected.txt
│       └── nordvpn-disconnected.txt
├── requirements.txt
├── README.md
└── SNARKYCTL.md
```

---

# Phase 1: Command-Layer Prototype

Before creating a web service, build a small Python command-line program that gathers and parses system status.

It should collect:

- `nordvpn status`
- `wg show`
- `systemctl is-active dnsmasq`
- `systemctl is-active nordvpnd`
- Current public IPv4 address
- Basic uptime and load information

Example command:

```bash
python -m app.commands status
```

Example output:

```json
{
  "nordvpn": {
    "connected": true,
    "server": "us9167",
    "hostname": "us9167.nordvpn.com",
    "country": "United States",
    "city": "Dallas",
    "technology": "NORDLYNX"
  },
  "wireguard": {
    "interface": "wg0",
    "peer_connected": true,
    "latest_handshake_seconds": 42
  },
  "public_ip": "2.56.190.136",
  "dnsmasq": "active",
  "nordvpnd": "active",
  "system": {
    "uptime_seconds": 48291
  }
}
```

Use `subprocess.run()` with:

- Argument arrays rather than shell strings.
- A reasonable timeout.
- Captured standard output and standard error.
- Explicit handling of nonzero exit status.
- No `shell=True`.

Example:

```python
subprocess.run(
    ["nordvpn", "status"],
    capture_output=True,
    text=True,
    timeout=15,
    check=False,
)
```

---

# Phase 2: Read-Only API

Create a FastAPI service with read-only endpoints.

Suggested endpoints:

```text
GET /api/status
GET /api/nordvpn/status
GET /api/wireguard/status
GET /api/public-ip
GET /api/services
GET /api/health
```

The combined status endpoint should return all dashboard data in one request.

Example:

```json
{
  "nordvpn": {
    "connected": true,
    "server": "us9167",
    "country": "United States",
    "city": "Dallas"
  },
  "wireguard": {
    "interface": "wg0",
    "peer_connected": true
  },
  "public_ip": "2.56.190.136",
  "services": {
    "dnsmasq": "active",
    "nordvpnd": "active"
  }
}
```

The health endpoint should return an appropriate HTTP status:

- `200` when the management service and dependencies are healthy.
- `503` when an essential dependency is unavailable.

---

# Phase 3: NordVPN Controls

Add restricted state-changing endpoints:

```text
POST /api/nordvpn/connect
POST /api/nordvpn/disconnect
```

A connection request should accept only a predefined alias:

```json
{
  "target": "dallas"
}
```

Do not accept arbitrary server strings directly from the browser.

Use a configuration file such as:

```yaml
servers:
  dallas:
    command_target: us9167
    label: Dallas, United States
  prague:
    command_target: Czech_Republic
    label: Prague, Czechia
  warsaw:
    command_target: Poland
    label: Warsaw, Poland
```

The backend must verify that the requested alias exists before executing anything.

Example safe execution:

```python
subprocess.run(
    ["sudo", "/usr/local/sbin/snark-nordvpn-connect", server_alias],
    capture_output=True,
    text=True,
    timeout=45,
    check=False,
)
```

Suggested behavior:

1. Validate the alias.
2. Start the connection command.
3. Wait for completion or timeout.
4. Query `nordvpn status`.
5. Return the resulting connection state.
6. Include readable error details when the operation fails.

---

# Phase 4: Web Dashboard

Create a simple dashboard served from the same FastAPI application.

Initial layout:

```text
┌────────────────────────────────────────────┐
│ Snarkypuss Control Panel                   │
│                                            │
│ WireGuard: Connected                       │
│ NordVPN: Dallas #9167                      │
│ Exit IP: 2.56.190.136                      │
│ DNS: Running                               │
│ VPS: Healthy                               │
│                                            │
│ [ Dallas ] [ Prague ] [ Warsaw ]           │
│ [ Disconnect NordVPN ]                     │
│                                            │
│ Last refresh: 21:42:17                     │
└────────────────────────────────────────────┘
```

Dashboard behavior:

- Refresh status periodically.
- Display a visible connecting state.
- Disable controls while a request is in progress.
- Show success and failure messages.
- Confirm destructive or disruptive operations.
- Clearly distinguish:
  - WireGuard state.
  - NordVPN state.
  - Public exit IP.
  - DNS service state.

Use browser `fetch()` calls to communicate with the API.

---

# Phase 5: Dedicated Service Account

Do not run the web application as `root`.

Create a dedicated system account:

```bash
sudo useradd --system \
  --home /opt/snarkypuss-control \
  --shell /usr/sbin/nologin \
  snarkctl
```

Set ownership appropriately:

```bash
sudo chown -R snarkctl:snarkctl /opt/snarkypuss-control
```

The application account should have no interactive shell and no general administrative privileges.

---

# Phase 6: Restricted Privileged Operations

Create wrapper scripts for every privileged action.

Suggested wrappers:

```text
/usr/local/sbin/snark-nordvpn-connect
/usr/local/sbin/snark-nordvpn-disconnect
/usr/local/sbin/snark-dnsmasq-restart
/usr/local/sbin/snark-system-status
```

Each wrapper should:

- Validate its arguments.
- Reject unknown targets.
- Use absolute command paths.
- Avoid evaluating shell expressions.
- Produce predictable output.
- Return meaningful exit codes.

Create:

```text
/etc/sudoers.d/snarkypuss-control
```

Permit only the exact wrappers required:

```sudoers
snarkctl ALL=(root) NOPASSWD: /usr/local/sbin/snark-nordvpn-connect *
snarkctl ALL=(root) NOPASSWD: /usr/local/sbin/snark-nordvpn-disconnect
snarkctl ALL=(root) NOPASSWD: /usr/local/sbin/snark-dnsmasq-restart
```

Do not grant:

```text
snarkctl ALL=(ALL) NOPASSWD: ALL
```

Validate the sudoers file:

```bash
sudo visudo -cf /etc/sudoers.d/snarkypuss-control
```

---

# Phase 7: Network Binding

Bind Uvicorn only to the WireGuard interface:

```text
10.8.0.1:8443
```

Example:

```bash
uvicorn app.main:app     --host 10.8.0.1     --port 8443
```

Do not use:

```text
0.0.0.0
```

Access the dashboard at:

```text
https://10.8.0.1:8443/
```

or through the Windows hosts-file alias:

```text
https://snarkypuss:8443/
```

No Linode Cloud Firewall rule should expose port `8443` publicly.

---

# Phase 8: Authentication and HTTPS

WireGuard provides network-level access control, but the dashboard should still require application authentication.

Initial authentication options:

1. Random bearer token.
2. Session login with a strong password.
3. HTTP basic authentication over HTTPS.

Recommended first version:

- Generate a long random bearer token.
- Store the server-side copy in a root-readable configuration file.
- Store the Windows copy in a protected local file.
- Require the token for every API request.

Later improvement:

- Mutual TLS.
- Client certificate required by the web server.
- Separate certificate per authorized management device.

Use HTTPS even though traffic already travels through WireGuard. This provides browser integrity checks and prevents accidental plaintext exposure if the binding changes later.

---

# Phase 9: systemd Service

Create:

```text
/etc/systemd/system/snarkypuss-control.service
```

Example:

```ini
[Unit]
Description=Snarkypuss Control Panel
After=network-online.target wg-quick@wg0.service nordvpnd.service
Wants=network-online.target
Requires=wg-quick@wg0.service

[Service]
Type=simple
User=snarkctl
Group=snarkctl
WorkingDirectory=/opt/snarkypuss-control
EnvironmentFile=-/etc/snarkypuss-control.env
ExecStart=/opt/snarkypuss-control/venv/bin/uvicorn app.main:app --host 10.8.0.1 --port 8443
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable snarkypuss-control.service
sudo systemctl start snarkypuss-control.service
```

Check it:

```bash
sudo systemctl status snarkypuss-control.service
sudo journalctl -u snarkypuss-control.service -n 100 --no-pager
```

---

# Phase 10: systemd Hardening

Once the service works, add hardening directives gradually:

```ini
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
```

These options may need adjustment depending on:

- Static-file paths.
- Configuration-file locations.
- Unix sockets.
- Wrapper scripts.
- Certificate storage.

Apply hardening incrementally and test after each change.

---

# Phase 11: Testing Strategy

## Unit Tests

Test parsers using saved command output:

- Connected NordVPN status.
- Disconnected NordVPN status.
- Malformed output.
- Missing fields.
- Command timeout.
- Nonzero command exit.

## API Tests

Test:

- Successful status response.
- NordVPN daemon unavailable.
- Invalid connection target.
- Connection timeout.
- Authentication failure.
- Successful disconnect.
- Repeated disconnect request.

## Operational Tests

Test real failures:

- Stop `nordvpnd`.
- Stop `dnsmasq`.
- Disconnect NordVPN.
- Connect to an unavailable server.
- Restart WireGuard.
- Reboot the VPS.
- Disconnect the Windows WireGuard client during an API operation.

## Critical Connectivity Test

The dashboard must remain reachable during:

- `nordvpn connect`
- `nordvpn disconnect`
- NordVPN server switching
- NordVPN daemon restart

The management path must remain:

```text
Windows → WireGuard → 10.8.0.1
```

It must not depend on the NordVPN exit path.

---

# Milestone Plan

## Milestone 1: Structured Status Command

Deliverable:

```bash
python -m app.commands status
```

Produces reliable JSON.

## Milestone 2: Read-Only API

Deliverable:

```text
GET /api/status
```

Available only on `10.8.0.1`.

## Milestone 3: Status Dashboard

Deliverable:

A browser page showing:

- WireGuard status.
- NordVPN status.
- Exit IP.
- DNS status.
- VPS health.

## Milestone 4: Restricted NordVPN Controls

Deliverable:

- Connect to predefined locations.
- Disconnect NordVPN.
- Show progress and errors.

## Milestone 5: Authentication and HTTPS

Deliverable:

- Encrypted browser connection.
- Authenticated API.
- Token or certificate management.

## Milestone 6: Privilege Separation

Deliverable:

- Dedicated `snarkctl` account.
- Restricted wrappers.
- Minimal sudo permissions.

## Milestone 7: Extended Management

Possible additions:

- Restart `dnsmasq`.
- Reload DNS blocklists.
- Show recent logs.
- Restart `nordvpnd`.
- Safe VPS reboot.
- Display traffic counters.
- Show latency to exit locations.

---

# Possible Later Features

- NordVPN location dropdown.
- Saved favourite servers.
- Latency test for predefined exits.
- WireGuard and NordLynx transfer counters.
- CPU, memory, disk, and load display.
- DNS blocklist-category toggles.
- Recent `systemd` log viewer.
- Safe reboot with confirmation.
- Direct Texas-exit mode with NordVPN disconnected.
- Warning when the apparent exit location is unexpected.
- Windows system-tray client.
- Desktop notifications after connection changes.
- Audit log of management actions.
- Multiple authorized WireGuard clients.
- Per-client permissions.

---

# Initial Implementation Priority

The first implementation should not begin with the visual dashboard.

Build and verify this sequence:

1. Reliable command execution.
2. Reliable command-output parsing.
3. Structured status data.
4. Read-only private API.
5. Status dashboard.
6. Restricted state-changing actions.
7. Authentication and HTTPS.
8. Privilege separation and systemd hardening.

Once the command and API layers are dependable, the dashboard becomes straightforward.
