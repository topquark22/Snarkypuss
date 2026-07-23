# SnarkyCtl Architecture

## Overview

SnarkyCtl is a small Python web application for monitoring and controlling the `snarkypuss` VPN gateway. It is reachable only through the existing WireGuard tunnel and does not expose a management port on the VPS's public interface.

The browser dashboard and the Linux command layer are the important parts. The remaining components provide structure, validation, authentication, and safe privilege separation around them.

```text
Windows browser
      │
      │ HTTPS through WireGuard
      ▼
Uvicorn web server on 10.8.0.1:8443
      │
      ▼
FastAPI application
      ├── Jinja2 dashboard templates
      ├── JSON status API
      ├── HTTP Basic authentication
      └── Python status and control logic
                    │
                    ▼
       Privileged control daemon
                    │
                    ▼
       Configured upstream VPN and selected Linux services
```

---

## Python 3

Python contains the application logic. It will:

- Read WireGuard status and request upstream-VPN status through the configured provider adapter.
- Interpret their output.
- Decide whether the gateway is in VPN, Direct VPS, or Locked mode.
- Return structured status information.
- Request narrowly defined privileged operations through the local control daemon.

For example, Python might convert:

```text
Status: Connected
Server: us9167.nordvpn.com
Country: United States
```

into:

```json
{
  "state": "connected",
  "server": "us9167",
  "country": "United States"
}
```

---

## FastAPI

FastAPI is the web-application framework. It maps HTTP requests to ordinary Python functions.

A simplified endpoint looks like:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/status")
def get_status():
    return {
        "vpn": "connected",
        "provider": "nordvpn",
        "mode": "vpn",
        "exit_ip": "2.56.190.136",
    }
```

When the browser requests:

```text
GET /api/status
```

FastAPI calls `get_status()` and converts the returned Python object into JSON.

FastAPI also provides:

- URL routing.
- Request validation.
- JSON serialization.
- HTTP error handling.
- Automatic API documentation during development.
- Integration with authentication and middleware.

FastAPI does not listen for network connections itself. That is Uvicorn's job.

---

## Uvicorn

Uvicorn is the network-facing web server process. It:

- Listens on `10.8.0.1:8443`.
- Receives HTTP or HTTPS requests.
- Passes them to FastAPI.
- Returns FastAPI's response to the browser.

The relationship is:

```text
Uvicorn = network-facing server
FastAPI = request-handling application
```

The command:

```bash
uvicorn snarkyctl.main:app --host 10.8.0.1 --port 8443 \
    --ssl-certfile /etc/snarkyctl/tls/server.crt \
    --ssl-keyfile /etc/snarkyctl/tls/server.key
```

means:

- Import the Python module `app.main`.
- Find the FastAPI object named `app`.
- Listen only on `10.8.0.1`.
- Use TCP port `8443`.

Uvicorn is lightweight and suitable for this single-user private dashboard. SnarkyCtl does not initially need Apache, nginx, or another application server.

---

## Pydantic

Pydantic defines and validates structured data. FastAPI uses it naturally.

For example:

```python
from pydantic import BaseModel


class ConnectRequest(BaseModel):
    target: str
```

If the browser submits:

```json
{
  "target": "dallas"
}
```

Pydantic verifies that the expected field exists and has the correct type. The application then performs the more important security check: whether `dallas` is an approved alias.

Pydantic can also define the status response:

```python
class GatewayStatus(BaseModel):
    desired_mode: str
    actual_mode: str
    forwarding_allowed: bool
    exit_ip: str | None
```

This prevents different parts of the application from inventing incompatible representations of the same state.

---

## Jinja2

Jinja2 produces HTML from a template. For example:

```html
<h1>SnarkyCtl</h1>
<p>Current mode: {{ mode }}</p>
```

If Python supplies `mode="VPN"`, the browser receives:

```html
<h1>SnarkyCtl</h1>
<p>Current mode: VPN</p>
```

SnarkyCtl will probably use Jinja2 only to deliver the initial dashboard page. HTTP Basic authentication is handled before the template is served. After the dashboard loads, its JavaScript will call the API periodically and update the displayed information.

---

## Plain HTML, CSS, and JavaScript

The dashboard uses standard browser technologies:

- **HTML** defines the status panels and controls.
- **CSS** controls layout, colours, warnings, and spacing.
- **JavaScript** retrieves current status and sends control requests.

For example:

```javascript
const response = await fetch("/api/status");
const status = await response.json();
```

The JavaScript then updates the page with the returned status.

Using plain JavaScript avoids React, Node.js, npm, frontend build pipelines, and a separate frontend application. Those components would add more machinery than value to a compact control panel.

---

## YAML Configuration

YAML is a human-readable configuration format:

```yaml
servers:
  dallas:
    label: Dallas, United States
  prague:
    label: Prague, Czechia
```

The application-side configuration provides approved choices and display labels. The security-sensitive mapping used by privileged commands remains root-owned.

JSON would work equally well. YAML is easier for a human to edit, particularly when comments are useful.

---

## Python Virtual Environment

The virtual environment is an isolated collection of Python packages located at:

```text
/usr/lib/snarkyctl/venv/
```

FastAPI, Uvicorn, and the other Python dependencies are installed there instead of modifying Ubuntu's system Python installation.

This prevents:

- Conflicts with Python packages used by Ubuntu.
- Application upgrades from altering the operating system.
- Uncertainty about which package versions the service uses.

The systemd service runs the Uvicorn executable from this environment:

```text
/usr/lib/snarkyctl/venv/bin/uvicorn
```

---

## systemd

`systemd` is Ubuntu's service manager. SnarkyCtl installs three coordinated units:

- `snarkyctl-web.service`: the HTTPS FastAPI/Uvicorn process running as `snarkyctl`.
- `snarkyctl-control.socket`: the protected Unix-domain socket at `/run/snarkyctl/control.sock`.
- `snarkyctl-control.service`: the deliberately small root control daemon, activated through the socket.

The web service can use `NoNewPrivileges=true` because it never calls `sudo` or otherwise attempts to gain privileges. The control daemon begins with the privilege it needs and exposes only the fixed local protocol.

Administrative commands include:

```bash
sudo systemctl start snarkyctl-control.socket snarkyctl-web.service
sudo systemctl stop snarkyctl-web.service snarkyctl-control.socket
sudo systemctl status snarkyctl-web.service snarkyctl-control.service
sudo journalctl -u snarkyctl-web.service
sudo journalctl -u snarkyctl-control.service
```

---

## The `snarkyctl` Service Account

`snarkyctl` is a dedicated Linux service account, not a human login account.

It:

- Cannot log in interactively.
- Does not know the root password.
- Cannot modify the application or privileged scripts.
- Runs the web server.
- Can invoke only specifically authorized operations.

If the web application has a vulnerability, an attacker initially obtains only the limited powers of `snarkyctl`, not unrestricted root access.

---

## Upstream VPN Provider Abstraction

The private client-to-VPS tunnel remains WireGuard. A separate optional **upstream VPN** carries forwarded Internet traffic beyond the VPS.

The root control daemon selects a trusted adapter through a fixed compiled registry:

```text
VpnProvider
├── NordVpnProvider
├── WireGuardProvider (future)
└── OpenVpnProvider (future)
```

Every adapter implements the same provider-neutral operations:

```python
status() -> VpnStatus
connect(target: VpnTarget) -> VpnStatus
disconnect() -> VpnStatus
```

Common states are `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, `FAILED`, and `UNKNOWN`. Provider-specific fields may appear only in a bounded details map; core policy does not depend on them.

Configuration selects a registry key such as `nordvpn`. It may not name an arbitrary Python module. Provider adapters execute inside the root daemon and are therefore trusted code shipped by the package.

The provider reports connection state and a verified upstream interface. It does not generate firewall rules. Firewall policy remains an independent core component.

---

## Privileged Control Daemon

The web application never executes privileged network commands directly. It sends a small, schema-validated request over:

```text
/run/snarkyctl/control.sock
```

The socket is owned by `root:snarkyctl` with mode `0660`. The control daemon also verifies Linux peer credentials and accepts only root or the configured `snarkyctl` UID.

The protocol exposes a fixed operation enumeration, for example:

```text
STATUS
LOCK
CONNECT dallas
DISCONNECT
DIRECT <confirmation-token>
```

It never accepts shell source, executable names, command-line fragments, firewall rules, filenames, or arbitrary provider targets. Requests have a protocol version, request identifier, strict size limit, validated fields, and bounded execution time.

The daemon:

- Runs as root in its own systemd service.
- Owns all mode-changing operations.
- Serializes concurrent operations.
- Validates aliases against root-owned configuration.
- Invokes commands with argument arrays and `shell=False`.
- Applies firewall changes atomically.
- Returns a structured result rather than raw command output.
- Logs security-relevant operations to the systemd journal.

The root daemon is intentionally much smaller than the network-facing application. It contains no HTML, templates, static files, HTTP server, authentication UI, or general command runner.

## Firewall-Enforced Modes

Locked behaviour is a property of the firewall rules, not merely a state remembered by Python:

- VPN mode permits forwarded client traffic only through the verified interface reported by the configured provider.
- If that interface disappears, the rule ceases to match and traffic is blocked immediately.
- Direct VPS mode uses a separate explicit rule for the configured public interface.
- Locked mode permits neither forwarding path.
- WireGuard management traffic remains permitted in every mode.

The public interface is explicitly configured and validated during preflight. It is never silently guessed while changing modes.

The control daemon applies each transition atomically. Boot begins Locked, and Direct VPS mode is never automatically restored.

---

## HTTPS and the Private Certificate Authority

WireGuard encrypts the network tunnel. HTTPS adds a second layer of protection and allows the browser to verify that it reached the intended dashboard.

Because `snarkypuss` is a private hostname, the project will create a small private certificate authority:

```text
Private SnarkyCtl CA
        │ signs
        ▼
snarkypuss server certificate
```

The CA certificate, but not its private key, is installed in Windows as a trusted root. The browser can then open:

```text
https://snarkypuss:8443/
```

without a certificate warning.

The CA private key remains protected and is not placed in the application directory.

---

## HTTP Basic Authentication

SnarkyCtl uses HTTP Basic authentication over HTTPS. The browser displays its standard username-and-password prompt and supplies the resulting `Authorization` header on subsequent requests.

There is no user database, login page, session cookie, or server-side session store. The authorized username and salted password hash are stored in a root-controlled file:

```text
/etc/snarkyctl/auth.htpasswd
```

The file uses the standard `htpasswd` format with a modern password hash. It never contains the plaintext password. Recommended ownership and permissions are:

```text
root:snarkyctl 0640
```

This allows the service account to verify credentials without allowing it to change the authorized password.

HTTP Basic authentication must never be used over plaintext HTTP because its credentials are encoded, not encrypted. HTTPS supplies the necessary transport encryption, while WireGuard provides an additional private network boundary.

State-changing endpoints will also require same-origin requests with JSON content and a dedicated request header. Cross-origin requests are rejected and CORS is not enabled. This prevents another website from using the browser's cached Basic credentials to trigger a control operation.

Changing the password means generating a new hash in the auth file. Because browsers cache Basic credentials, fully clearing an authenticated browser state may require closing the browser or using a private browsing window.

---

## Pytest

Pytest is the testing framework. It allows parsers and policy decisions to be tested without manipulating the real VPN.

For example:

```python
def test_failed_vpn_connection_locks_forwarding():
    status = handle_connection_failure()

    assert status.actual_mode == "locked"
    assert status.forwarding_allowed is False
```

Saved samples of real command output allow the parser to be tested repeatedly without requiring a real upstream VPN to connect during every test.

---

## Operating Modes

The architecture distinguishes policy from observed connectivity:

| Mode | Behaviour |
|---|---|
| **VPN** | Forwarded traffic exits through the configured upstream provider. If it fails, traffic becomes Locked. |
| **Direct VPS** | Forwarded traffic deliberately exits through the VPS public IP after explicit confirmation. |
| **Locked** | Forwarded Internet traffic is blocked while WireGuard management remains available. |

An observed upstream-VPN disconnection does not automatically select Direct VPS mode. Unexpected disconnects, failed connections, timeouts, and reboots default to Locked.

The status API therefore keeps desired and actual state separate:

```json
{
  "desired_mode": "vpn",
  "actual_mode": "locked",
  "vpn": { "provider": "nordvpn", "state": "DISCONNECTED" },
  "forwarding_allowed": false,
  "exit_ip": null
}
```

---

## Deliberately Excluded Components

The first version does not need:

- A database.
- Docker.
- Kubernetes.
- nginx or Apache.
- React, Vue, or Angular.
- Node.js or npm.
- Redis or a job queue.
- A cloud authentication provider.

The resulting system remains a small Python HTTPS service, one HTML template, a little JavaScript, a deliberately small root control daemon, and three coordinated systemd units. FastAPI and Uvicorn provide structure without turning SnarkyCtl into a large web-development project.
