# Snarkypuss Control Panel

## Project Goal

Turn the `snarkypuss` VPS into a remotely controlled network appliance with a small private API and web dashboard.

The management interface will be reachable only through the existing WireGuard tunnel:

```text
Windows browser
      ↓ HTTPS over WireGuard
10.8.0.1 management service
      ↓
NordVPN CLI and selected system services
```

The first release will support:

- Displaying NordVPN connection status.
- Connecting NordVPN to a predefined server or location.
- Disconnecting NordVPN.
- Displaying the current public IPv4 address.
- Displaying WireGuard interface and peer activity.
- Displaying essential VPS health information.

Restarting `dnsmasq`, viewing logs, restarting services, and rebooting the VPS are deliberately deferred until the core control path is proven safe and reliable.

---

## Core Safety Invariants

The following are requirements, not optional enhancements.

1. **The control plane survives NordVPN changes**

   The dashboard must remain reachable over `wg0` while NordVPN connects, disconnects, changes servers, restarts, or modifies routes and firewall rules.

   The management path must always remain:

   ```text
   Windows → WireGuard → 10.8.0.1
   ```

   It must not depend on the NordVPN exit path.

2. **Private by default**

   The service must listen only on the WireGuard address:

   ```text
   10.8.0.1
   ```

   It must never listen on the public interface or on `0.0.0.0`. Port `8443` must not be exposed by the Linode Cloud Firewall or the VPS firewall.

3. **No arbitrary shell execution**

   The API exposes a fixed set of operations. User-supplied text is never interpolated into a shell command. Commands use argument arrays, absolute executable paths, timeouts, and `shell=False`.

4. **Least privilege from the beginning**

   The web application never runs as `root`. Privileged operations are available only through root-owned, non-writable wrapper programs with a strict allowlist.

5. **No unauthenticated state changes**

   Read-only development endpoints may temporarily rely on WireGuard access control. No state-changing endpoint may be enabled unless application authentication is configured and tested.

6. **Read-only first**

   Status collection, parsing, and failure reporting must be dependable before connect or disconnect controls are added.

7. **Fail visibly and degrade gracefully**

   A failed dependency must not erase otherwise valid status. Each subsystem reports its own state, check time, and controlled error. Full command output and raw `stderr` remain in server-side logs.

8. **Serialize control operations**

   Only one NordVPN-changing operation may run at a time. Concurrent requests receive HTTP `409 Conflict`; disconnect is idempotent.

---

## Recommended Technology Stack

- Python 3
- FastAPI
- Uvicorn
- Pydantic models
- Jinja2 templates
- Plain HTML and CSS
- Minimal browser JavaScript
- YAML or JSON configuration
- `systemd`
- `pytest`

Do not add a database initially. Server aliases and display metadata belong in a small configuration file; transient command serialization can use a process or filesystem lock.

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
│   ├── operations.py
│   ├── static/
│   │   ├── dashboard.js
│   │   └── style.css
│   └── templates/
│       ├── login.html
│       └── index.html
├── config/
│   └── servers.yaml
├── tests/
│   ├── test_commands.py
│   ├── test_api.py
│   ├── test_security.py
│   ├── test_operations.py
│   └── fixtures/
│       ├── nordvpn-connected.txt
│       └── nordvpn-disconnected.txt
├── requirements.txt
├── README.md
└── SNARKYCTL.md
```

Privileged wrappers are installed separately under `/usr/local/sbin`; secrets and authoritative privileged configuration do not live in the application tree.

---

# Phase 1: Environment Survey and Connectivity Invariant

Before writing the application, record the VPS's actual configuration:

- Public and private interfaces and addresses.
- `wg0` address, peer networks, and listen port.
- Main and policy routing tables.
- Firewall implementation and active rules.
- NordVPN technology, kill-switch setting, routing behaviour, and daemon service name.
- Exact paths and representative output for `nordvpn`, `wg`, `systemctl`, `ip`, and the chosen public-IP client.
- DNS configuration in both NordVPN-connected and disconnected states.

Capture a diagnostic baseline using read-only commands such as:

```bash
ip -brief address
ip route show table all
ip rule show
wg show
nordvpn settings
nordvpn status
systemctl status nordvpnd --no-pager
```

Then prove manually that the WireGuard management path survives:

- `nordvpn connect`
- `nordvpn disconnect`
- Switching NordVPN servers.
- Restarting `nordvpnd`.
- NordVPN kill-switch and firewall changes.
- A VPS reboot.

Verify specifically that:

- Incoming WireGuard packets remain accepted on the VPS public interface.
- Replies to the Windows WireGuard client leave through `wg0`.
- Policy routing does not send those replies through NordLynx.
- NordVPN firewall rules do not block the WireGuard control path.
- DNS behaves correctly in connected and disconnected modes.

Do not proceed to remote state-changing controls until this invariant is demonstrated.

---

# Phase 2: Structured Status Library

Build a Python command layer that gathers and parses system status before creating a web service.

It should collect:

- `nordvpn status`
- `wg show`
- `systemctl is-active nordvpnd`
- Current public IPv4 address
- Uptime, load, memory, and disk information as needed

Example command:

```bash
python -m app.commands status
```

Example output:

```json
{
  "nordvpn": {
    "state": "connected",
    "server": "us9167",
    "hostname": "us9167.nordvpn.com",
    "country": "United States",
    "city": "Dallas",
    "technology": "NORDLYNX",
    "checked_at": "2026-07-22T10:42:11Z"
  },
  "wireguard": {
    "interface": "wg0",
    "interface_up": true,
    "peer_configured": true,
    "latest_handshake_at": "2026-07-22T10:41:29Z",
    "handshake_age_seconds": 42,
    "recently_active": true
  },
  "public_ip": {
    "address": "2.56.190.136",
    "version": 4,
    "checked_at": "2026-07-22T10:42:11Z"
  },
  "services": {
    "nordvpnd": "active"
  },
  "system": {
    "uptime_seconds": 48291
  }
}
```

WireGuard has no persistent connected state. `recently_active` is only an interpretation of handshake age using a documented threshold, initially 180 seconds. The raw handshake time and age must also be returned.

Use `subprocess.run()` with:

- Argument arrays rather than shell strings.
- Absolute executable paths where practical.
- A bounded timeout for every command.
- Captured standard output and standard error.
- Explicit handling of nonzero exit status.
- `shell=False`.

```python
subprocess.run(
    ["/usr/bin/nordvpn", "status"],
    capture_output=True,
    text=True,
    timeout=15,
    check=False,
    shell=False,
)
```

Independent checks should run concurrently so that a slow public-IP provider does not delay local status. The combined result should contain partial data when one check fails.

Use a controlled error structure:

```json
{
  "state": "unavailable",
  "checked_at": "2026-07-22T10:42:11Z",
  "error_code": "COMMAND_TIMEOUT",
  "message": "NordVPN status check timed out"
}
```

Do not send raw command `stderr` to the browser. Log detailed diagnostics server-side.

## Public-IP behaviour

Define explicitly:

- IPv4 is the first-release target.
- Requests follow the current default route, so the result represents the apparent exit address.
- Each request has a short timeout.
- A second independent provider is used as fallback.
- Failure is reported only for the public-IP component, not the whole status response.
- A later check may compare the observed address or location with the expected NordVPN state.

---

# Phase 3: Privilege Boundary

Create the security boundary before adding state-changing API routes.

## Dedicated account

```bash
sudo useradd --system \
  --home /opt/snarkypuss-control \
  --shell /usr/sbin/nologin \
  snarkctl
```

Ownership must prevent a compromised web process from modifying executable code or privileged configuration:

- Application code: `root:root`, not writable by `snarkctl`.
- Privileged wrappers: `root:root`, mode `0755`, never writable by `snarkctl`.
- Secrets: `root:snarkctl`, mode `0640`.
- Writable runtime directory, if required: owned by `snarkctl` and narrowly scoped.
- Logs: use the systemd journal unless a separate log directory is necessary.

Do not recursively make the service account owner of `/opt/snarkypuss-control`.

## Restricted wrappers

Install one root-owned wrapper for each privileged action:

```text
/usr/local/sbin/snark-nordvpn-connect
/usr/local/sbin/snark-nordvpn-disconnect
```

Later privileged operations, such as restarting `dnsmasq`, require separate wrappers and a separate security review.

Each wrapper must:

- Validate every argument.
- Accept only predefined aliases.
- Use an authoritative root-owned allowlist.
- Reject extra or malformed arguments.
- Use absolute command paths.
- Avoid `eval`, shell expansion, and command substitution.
- Produce predictable output and meaningful exit codes.
- Be independently safe even if the application is compromised.

Avoid inconsistent duplicate allowlists. The privileged wrapper or its root-owned configuration is authoritative; application configuration may add display labels but must not broaden the privileged choices.

Create `/etc/sudoers.d/snarkypuss-control` with only the exact commands required. For example:

```sudoers
Defaults:snarkctl secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
snarkctl ALL=(root) NOPASSWD: /usr/local/sbin/snark-nordvpn-connect *
snarkctl ALL=(root) NOPASSWD: /usr/local/sbin/snark-nordvpn-disconnect
```

The wildcard makes strict wrapper-side validation essential. Never grant:

```text
snarkctl ALL=(ALL) NOPASSWD: ALL
```

Validate the file:

```bash
sudo visudo -cf /etc/sudoers.d/snarkypuss-control
```

---

# Phase 4: Read-Only Private API

Create a FastAPI service bound only to `10.8.0.1`.

Initial endpoints:

```text
GET /api/status
GET /api/health/live
GET /api/health/ready
```

Optional component endpoints may be added if they prove useful, but the dashboard should normally retrieve all display data through one `/api/status` request.

Health semantics:

- `/api/health/live` answers whether the management application is running.
- `/api/health/ready` answers whether the application can perform its essential local checks.
- `/api/status` reports each dependency independently and normally returns structured partial results rather than converting every dependency failure into HTTP `503`.

Bind Uvicorn only to:

```text
10.8.0.1:8443
```

```bash
uvicorn app.main:app --host 10.8.0.1 --port 8443
```

Never use `0.0.0.0`. Verify the actual listener with `ss` and verify from an external host that the public VPS address does not accept connections on port `8443`.

---

# Phase 5: Authentication

WireGuard provides network-level access control, but application authentication is still required before control endpoints are enabled.

For the first browser-based version, use:

- A login page with a strong password.
- A slow password hash stored in root-controlled configuration.
- An `HttpOnly`, `Secure`, `SameSite=Strict` session cookie.
- CSRF protection for state-changing requests.
- A short, configurable session lifetime.
- Rate limiting or progressive delay for failed logins.

Do not store a long-lived bearer token in browser JavaScript or `localStorage`. A bearer token entered once and exchanged for a protected session cookie is an acceptable alternative.

Later improvements may include mutual TLS and a separate client certificate per authorized management device.

No state-changing route may be registered or enabled until authentication and CSRF tests pass.

---

# Phase 6: Status Dashboard

Serve a small dashboard from the same FastAPI application.

```text
┌────────────────────────────────────────────┐
│ Snarkypuss Control Panel                   │
│                                            │
│ WireGuard: Active  • handshake 42s ago     │
│ NordVPN: Dallas #9167                      │
│ Exit IPv4: 2.56.190.136                    │
│ VPS: Healthy                               │
│                                            │
│ [ Dallas ] [ Prague ] [ Warsaw ]           │
│ [ Disconnect NordVPN ]                     │
│                                            │
│ Last refresh: 21:42:17                     │
└────────────────────────────────────────────┘
```

Initially, the controls may be displayed as disabled until Phase 7.

Dashboard behaviour:

- Refresh status periodically without overlapping requests.
- Show the age of the last successful check.
- Distinguish WireGuard interface state, recent peer activity, NordVPN state, exit IPv4, and VPS health.
- Preserve valid component data when another component fails.
- Display controlled success and failure messages.
- Mark stale data clearly.

Use browser `fetch()` calls against same-origin API endpoints.

---

# Phase 7: Serialized NordVPN Controls

Add authenticated state-changing endpoints:

```text
POST /api/nordvpn/connect
POST /api/nordvpn/disconnect
```

A connection request accepts only a predefined alias:

```json
{
  "target": "dallas"
}
```

Display configuration may look like:

```yaml
servers:
  dallas:
    label: Dallas, United States
  prague:
    label: Prague, Czechia
  warsaw:
    label: Warsaw, Poland
```

The authoritative alias-to-NordVPN-target mapping remains root-owned at the privileged boundary. The browser never submits arbitrary server names or raw command arguments.

Execution example:

```python
subprocess.run(
    ["/usr/bin/sudo", "/usr/local/sbin/snark-nordvpn-connect", server_alias],
    capture_output=True,
    text=True,
    timeout=45,
    check=False,
    shell=False,
)
```

Required behaviour:

1. Authenticate the request and validate CSRF protection.
2. Validate the alias at the application boundary.
3. Acquire the single control-operation lock.
4. Return HTTP `409 Conflict` if another operation is active.
5. Execute the restricted wrapper with a bounded timeout.
6. Query status after completion or failure.
7. Return the resulting state and a controlled error message.
8. Release the lock reliably.

Disconnecting an already disconnected client should succeed idempotently. The dashboard disables controls and displays a connecting or disconnecting state while an operation is active.

---

# Phase 8: HTTPS and Certificate Trust

Use HTTPS even inside WireGuard. This supplies browser integrity checks and protects against accidental plaintext exposure if network configuration changes later.

The initial deployment must include a concrete trust plan:

1. Create a small private certificate authority or a deliberately trusted self-signed certificate.
2. Install its trust anchor in the Windows trusted-root store.
3. Issue the server certificate with Subject Alternative Names matching how the dashboard is opened.

If the Windows hosts file contains:

```text
10.8.0.1 snarkypuss
```

the certificate must include `snarkypuss` as a DNS SAN. It may also include `10.8.0.1` as an IP SAN.

Access the dashboard at:

```text
https://snarkypuss:8443/
```

Do not train the operator to ignore certificate warnings. Protect the private key as a secret readable only by the service through the minimum necessary group permissions.

---

# Phase 9: systemd Service and Hardening

Create `/etc/systemd/system/snarkypuss-control.service`:

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

Enable and inspect it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now snarkypuss-control.service
sudo systemctl status snarkypuss-control.service
sudo journalctl -u snarkypuss-control.service -n 100 --no-pager
```

Add hardening directives incrementally:

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

Important: `NoNewPrivileges=true` may prevent the service from using `sudo`, even for an allowlisted command. Test this explicitly. If it conflicts with the wrapper design, use a narrowly designed root helper or another explicit privilege-separation mechanism rather than silently weakening the boundary.

Review writable paths, certificate access, runtime locks, and Unix sockets before enabling each restriction.

---

# Phase 10: Testing Strategy

## Unit tests

Test parsers and command handling using saved output:

- Connected and disconnected NordVPN status.
- Multiple NordVPN output versions or formats actually observed on the VPS.
- WireGuard with a recent, old, or absent handshake.
- Malformed output and missing fields.
- Command timeout and nonzero exit.
- Public-IP primary failure and fallback success.
- Complete public-IP failure without loss of local status.

## API and security tests

Test:

- Successful and partially degraded status responses.
- Liveness versus readiness semantics.
- Authentication success and failure.
- Cookie security attributes.
- CSRF rejection.
- Invalid connection target.
- Connection timeout.
- Successful and repeated disconnect.
- Two simultaneous operations, with the second receiving `409`.
- Controlled browser errors that do not expose raw command output.

## Privilege tests

From the `snarkctl` account, verify that:

- Approved wrappers work.
- Unknown aliases and extra arguments fail.
- Direct privileged commands fail.
- Application code, wrappers, privileged configuration, and secrets cannot be modified.
- No general-purpose sudo command is available.

## Operational tests

Test real failures:

- Stop `nordvpnd`.
- Disconnect NordVPN.
- Connect to an unavailable target.
- Restart WireGuard.
- Reboot the VPS.
- Disconnect the Windows WireGuard client during an API operation.
- Expire or corrupt the browser session.
- Make the public-IP providers unavailable.

## Critical connectivity regression test

For every networking change, verify that the dashboard remains reachable during:

- `nordvpn connect`
- `nordvpn disconnect`
- NordVPN server switching
- NordVPN daemon restart
- Kill-switch or firewall rule reload

This test is required before release and after any change to routing, WireGuard, NordVPN, firewall, or systemd network ordering.

---

# Milestone Plan

## Milestone 1: Environment and Connectivity Baseline

Deliverables:

- Recorded interface, route, firewall, WireGuard, NordVPN, and DNS state.
- Demonstrated management connectivity through NordVPN transitions.
- Representative command-output fixtures.

## Milestone 2: Structured Status Command

Deliverable:

```bash
python -m app.commands status
```

It produces typed, reliable, partially degradable JSON.

## Milestone 3: Privilege Boundary

Deliverables:

- Dedicated `snarkctl` account.
- Root-owned application and wrapper files.
- Authoritative root-owned target allowlist.
- Minimal, validated sudo permissions.

## Milestone 4: Authenticated Read-Only API

Deliverables:

- `GET /api/status`
- Liveness and readiness endpoints.
- Service available only at `10.8.0.1`.
- Password-backed secure session authentication.

## Milestone 5: Status Dashboard

Deliverable: a browser page showing WireGuard activity, NordVPN status, exit IPv4, and VPS health, including partial failures and stale-data indicators.

## Milestone 6: Restricted NordVPN Controls

Deliverables:

- Connect to predefined aliases.
- Idempotent disconnect.
- Serialized operations and HTTP `409` handling.
- Progress and controlled error reporting.

## Milestone 7: Trusted HTTPS and Hardened Deployment

Deliverables:

- A certificate trusted by the Windows management computer.
- Authenticated and encrypted browser connection.
- A systemd unit with tested hardening.
- Confirmation that port `8443` is not publicly reachable.

## Milestone 8: Extended Management

Possible additions, each requiring its own wrapper and security review:

- Display and restart `dnsmasq`.
- Reload DNS blocklists.
- Show narrowly filtered recent logs.
- Restart `nordvpnd`.
- Safe VPS reboot.
- Display traffic counters.
- Show latency to predefined exit locations.

---

# Possible Later Features

- NordVPN location dropdown backed by approved aliases.
- Saved favourite servers.
- Latency tests for predefined exits.
- WireGuard and NordLynx transfer counters.
- CPU, memory, disk, and load graphs.
- DNS blocklist-category toggles.
- Safe, filtered log viewer.
- Safe reboot with explicit confirmation.
- Direct US-exit mode with NordVPN disconnected.
- Warning when the apparent exit location is unexpected.
- Windows system-tray client.
- Desktop notifications after connection changes.
- Audit log of management actions.
- Multiple authorized WireGuard clients.
- Per-client permissions or certificates.

---

# Initial Implementation Priority

Build and verify in this order:

1. Survey the real network and service environment.
2. Prove the WireGuard control-path invariant.
3. Implement reliable command execution and parsing.
4. Produce typed, partially degradable status data.
5. Establish the dedicated account and privileged boundary.
6. Build the private read-only API.
7. Add authentication and CSRF protection.
8. Build the status dashboard.
9. Add serialized, restricted NordVPN controls.
10. Establish trusted HTTPS and harden the systemd service.
11. Run connectivity, privilege, security, and failure tests.

The visual dashboard is intentionally not the first implementation task. The difficult part is preserving the WireGuard management path while NordVPN modifies routing and firewall policy; that requirement governs the architecture and release criteria.
