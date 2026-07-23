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
       Restricted root-owned wrappers
                    │
                    ▼
       NordVPN and selected Linux services
```

---

## Python 3

Python contains the application logic. It will:

- Run status commands such as `nordvpn status` and `wg show`.
- Interpret their output.
- Decide whether the gateway is in NordVPN, Direct VPS, or Locked mode.
- Return structured status information.
- Invoke narrowly restricted control wrappers.

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
        "nordvpn": "connected",
        "mode": "nordvpn",
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

`systemd` is Ubuntu's service manager. It already manages services such as WireGuard and NordVPN.

For SnarkyCtl it will:

- Start the dashboard after boot.
- Run it as the `snarkyctl` account.
- Restart it if it crashes.
- Capture its logs.
- Apply operating-system security restrictions.

The principal administrative commands will be:

```bash
sudo systemctl start snarkyctl
sudo systemctl stop snarkyctl
sudo systemctl status snarkyctl
sudo journalctl -u snarkyctl
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

## Root-Owned Wrapper Programs

FastAPI will not execute commands such as:

```bash
sudo nordvpn connect USER_SUPPLIED_TEXT
```

Instead, it invokes a fixed wrapper:

```bash
sudo /usr/libexec/snarkyctl/snark-nordvpn-connect dallas
```

The wrapper independently verifies that `dallas` is permitted and translates it into the actual NordVPN target.

This creates two validation boundaries:

1. FastAPI rejects invalid requests.
2. The privileged wrapper rejects them again.

Even if someone compromises the FastAPI process, the wrapper does not become a general root shell.

---

## Restricted sudoers Rules

The sudoers file grants the `snarkyctl` account permission to run only approved wrappers:

```sudoers
snarkyctl ALL=(root) NOPASSWD: /usr/libexec/snarkyctl/snark-nordvpn-connect *
snarkyctl ALL=(root) NOPASSWD: /usr/libexec/snarkyctl/snark-nordvpn-disconnect
```

It does not grant general `sudo` access. The wrappers must independently reject unknown aliases, malformed input, and extra arguments.

The sudoers file will be validated before use:

```bash
sudo visudo -cf /etc/sudoers.d/snarkyctl
```

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
| **NordVPN** | Forwarded traffic exits through NordVPN. If NordVPN fails, traffic becomes Locked. |
| **Direct VPS** | Forwarded traffic deliberately exits through the VPS public IP after explicit confirmation. |
| **Locked** | Forwarded Internet traffic is blocked while WireGuard management remains available. |

An observed NordVPN disconnection does not automatically select Direct VPS mode. Unexpected disconnects, failed connections, timeouts, and reboots default to Locked.

The status API therefore keeps desired and actual state separate:

```json
{
  "desired_mode": "nordvpn",
  "actual_mode": "locked",
  "nordvpn_state": "disconnected",
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

The resulting system remains a small Python service, two HTML templates, a little JavaScript, several carefully restricted Linux wrappers, and a systemd unit. FastAPI and Uvicorn provide structure without turning SnarkyCtl into a large web-development project.
