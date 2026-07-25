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
       Protected Unix control socket
                    │
                    ▼
       Privileged control daemon
                    │
                    ▼
       NordVPN and selected Linux services
```

---

## Python 3

Python contains the application logic. It:

- Runs provider status and settings commands through the compiled adapter.
- Interpret their output.
- Decide whether the gateway is in NordVPN, Direct VPS, or Locked mode.
- Return structured status information.
- Sends and receives typed messages across the protected Unix socket.

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


@app.get("/api/v2/status")
def get_status():
    return {
        "vpn_status": {
            "provider": "nordvpn",
            "state": "CONNECTED",
            "gateway_mode": "VPN",
            "target": "dallas",
        }
    }
```

When the browser requests:

```text
GET /api/v2/status
```

FastAPI calls `get_status()` and converts the returned Python object into JSON.

FastAPI also provides:

- URL routing.
- Request validation.
- JSON serialization.
- HTTP error handling.
- Typed response validation.
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
uvicorn app.main:app --host 10.8.0.1 --port 8443
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

If Python supplies `mode="NordVPN"`, the browser receives:

```html
<h1>SnarkyCtl</h1>
<p>Current mode: NordVPN</p>
```

SnarkyCtl uses Jinja2 only to deliver the initial dashboard page. HTTP Basic authentication is handled before the template is served. After the dashboard loads, its JavaScript polls status, retrieves the approved target catalogue, and sends provider-neutral connect requests.

---

## Plain HTML, CSS, and JavaScript

The dashboard uses standard browser technologies:

- **HTML** defines the status panels and controls.
- **CSS** controls layout, colours, warnings, and spacing.
- **JavaScript** retrieves current status and sends control requests.

For example:

```javascript
const response = await fetch("/api/v2/status");
const status = await response.json();
```

The JavaScript then updates the page with the returned status.

Using plain JavaScript avoids React, Node.js, npm, frontend build pipelines, and a separate frontend application. Those components would add more machinery than value to a compact control panel.

---

## Configuration and target storage

The root-owned YAML document contains service, network, and provider settings. VPN
destinations are stored separately in `/var/lib/snarkyctl/targets.db`.

SQLite stores provider-neutral aliases and labels together with structured, provider-owned
selectors. The browser receives aliases and display labels for ordinary connection
selection. Only authenticated administrative operations can retrieve or replace selector
documents, and only the privileged daemon opens the database.

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

`systemd` is Ubuntu's service manager. It already manages services such as WireGuard and NordVPN.

For SnarkyCtl it will:

- Activate the root control daemon through its protected Unix socket.
- Start the dashboard after boot.
- Run the web service as the `snarkyctl` account.
- Restart it if it crashes.
- Capture its logs.
- Apply operating-system security restrictions.

The principal administrative commands are:

```bash
sudo systemctl start snarkyctl-control.socket
sudo systemctl start snarkyctl-web.service
sudo systemctl status snarkyctl-control.socket snarkyctl-control.service
sudo systemctl status snarkyctl-web.service
sudo journalctl -u snarkyctl-control.service -u snarkyctl-web.service
```

---

## The `snarkyctl` Service Account

`snarkyctl` is a dedicated Linux service account, not a human login account.

It:

- Cannot log in interactively.
- Does not know the root password.
- Cannot modify the application or root-owned configuration.
- Runs the web server.
- Can submit only typed protocol operations through the protected control socket.

If the web application has a vulnerability, an attacker initially obtains only the limited powers of `snarkyctl`, not unrestricted root access.

---

## Privileged Control Daemon

FastAPI does not run provider commands and the web service has no sudo privilege. It sends
strictly validated, versioned requests to:

```text
/run/snarkyctl/control.sock
```

The root control daemon verifies the connecting Unix peer, accepts only fixed protocol
operations, and performs a second authoritative target lookup. For example, the browser
and web process submit the alias `dallas`; only the daemon can resolve that alias to the
provider-specific command argument.

Control protocol version 3 adds the privileged `TARGET_SCHEMA`, `TARGET_CATALOG_GET`, and
`TARGET_CATALOG_REPLACE` operations. Complete catalogue replacement is bounded to 100
targets and uses an expected revision. The daemon validates every structured selector
through the compiled active-provider adapter, commits through `TargetRepository`, and only
then replaces its in-memory snapshot. Storage failure or a stale revision leaves the
previous snapshot active. The existing `TARGETS` operation remains selector-free.

The configured `targets.backend: sqlite` repository is opened explicitly at daemon startup.
Database existence alone never changes configuration, and the web process never opens the
database.

This creates three validation boundaries:

1. FastAPI rejects malformed browser requests and aliases.
2. The versioned control protocol rejects unknown operations and extra fields.
3. The privileged daemon rejects unknown aliases before invoking the adapter.

Provider commands use fixed executable paths, argument arrays, bounded timeouts, and
`shell=False`. The protocol cannot carry executable names, shell text, environment
assignments, or raw provider targets.

---

## Serialized Operations

The daemon handles local socket connections concurrently so status and target-catalogue
reads remain available during a provider transition. A non-blocking operation lock admits
only one connect, disconnect, or catalogue-replacement mutation at a time. Competing mutations receive
`OPERATION_IN_PROGRESS`, which the HTTP API maps to `409 Conflict`. The lock is released
in a `finally` block after success, timeout, provider failure, or an unexpected exception.

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

State-changing endpoints require JSON content and
`X-SnarkyCtl-Request: 1`. Browser requests must also carry same-origin Fetch Metadata and
an `Origin` matching the service when that header is present. Cross-origin requests are
rejected and CORS is not enabled. This prevents another website from using the browser's
cached Basic credentials to trigger a control operation.

Changing the password means generating a new hash in the auth file. Because browsers cache Basic credentials, fully clearing an authenticated browser state may require closing the browser or using a private browsing window.

---

## Pytest

Pytest is the testing framework. It allows parsers and policy decisions to be tested without manipulating the real VPN.

For example:

```python
def test_failed_nordvpn_connection_locks_forwarding():
    status = handle_connection_failure()

    assert status.actual_mode == "locked"
    assert status.forwarding_allowed is False
```

Saved samples of real command output allow the parser to be tested repeatedly without requiring NordVPN to connect during every test.

---

## Operating Modes

The architecture distinguishes policy from observed connectivity:

| Mode | Behaviour |
|---|---|
| **Protected VPN** | Leak protection is enabled before the configured upstream VPN connects. |
| **Direct VPS** | Forwarded traffic deliberately exits through the VPS public IP after explicit confirmation. |
| **Locked** | Leak protection is enabled before the upstream VPN disconnects, blocking public forwarding. |

The privileged daemon performs and verifies each ordered transition. Direct VPS requires
the exact confirmation phrase `EXPOSE VPS IP`; if its disconnect or final verification
fails after protection is disabled, the daemon attempts to restore protection. An
unexpected VPN disconnection never automatically selects Direct VPS mode.

The status API reports the observed provider-neutral state:

```json
{
  "vpn_status": {
    "provider": "nordvpn",
    "state": "DISCONNECTED",
    "gateway_mode": "LOCKED",
    "leak_protection_active": true
  },
  "public_ip_exposed": false
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

The resulting system remains a small Python application, one HTML template, a little
JavaScript, a privileged control daemon, and three systemd units. FastAPI and Uvicorn
provide structure without turning SnarkyCtl into a large web-development project.
