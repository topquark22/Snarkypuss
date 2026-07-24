# SnarkyCtl Requirements

## 1. Purpose

SnarkyCtl is a private control plane for observing and controlling an optional upstream
VPN on the `snarkypuss` Linux gateway.

It provides:

- An authenticated HTTPS dashboard.
- Provider-neutral VPN and gateway status.
- A catalogue of administrator-approved VPN targets.
- Connection and target switching through the dashboard and CLI.
- Guarded disconnection through the CLI.
- Public exit IPv4, DNS service state, and basic VPS health.
- A least-privilege boundary between the network-facing web process and provider commands.

SnarkyCtl manages the upstream VPN. The gateway's underlying private management network is
an external prerequisite and is not configured, monitored, or controlled by this project.

## 2. Current Scope

The development release implements:

- The built-in NordVPN adapter.
- A compiled registry of trusted provider adapters.
- Root-owned YAML configuration and target definitions.
- A socket-activated privileged control daemon.
- An unprivileged FastAPI and Uvicorn web service.
- HTTP Basic authentication backed by an `htpasswd` file.
- Provider-neutral status and target APIs.
- Dashboard connection and target switching.
- Serialized provider mutations with HTTP `409 Conflict`.
- External public-IP detection with TLS certificate verification.
- Preflight validation, systemd units, wheel builds, and Debian packaging.

The following remain outside the current implementation:

- Intentional Direct VPS mode.
- Dashboard disconnection.
- Persistent default targets or DNS preferences.
- Dashboard editing of the target catalogue.
- Runtime installation of provider adapters.
- Restarting unrelated services or rebooting the VPS.

## 3. Safety Invariants

### 3.1 Private management surface

The HTTPS service must bind only to the configured private management address. It must
never bind to `0.0.0.0`, a wildcard IPv6 address, or the VPS public address. The hosting
firewall and VPS firewall must not expose the management port publicly.

Changing VPN targets, reconnecting the provider, provider failures, and provider firewall
changes must not make the independent management path depend on the upstream VPN exit.

### 3.2 No arbitrary execution

No browser, API, CLI, or configuration field may supply:

- An executable path.
- Shell source text.
- Command options.
- Environment assignments.
- A Python module or plugin name.
- An unvalidated provider target.

Provider commands use a compiled adapter, a fixed executable path, argument arrays,
bounded timeouts, captured output, and `shell=False`.

### 3.3 Least privilege

The web service runs as the dedicated `snarkyctl` account and has no sudo privilege. It
communicates with the root control daemon only through:

```text
/run/snarkyctl/control.sock
```

The socket is owned by `root:snarkyctl`, has mode `0660`, and resides in a directory that
permits traversal by the `snarkyctl` group. The daemon verifies Linux peer credentials and
accepts only root or the configured service UID.

### 3.4 No silent public-IP fallback

An upstream VPN disconnection is an observed condition, not permission to use the VPS
public connection.

| Gateway mode | Meaning |
|---|---|
| `VPN` | The upstream VPN is connected. |
| `LOCKED` | Public Internet forwarding is blocked by verified provider leak protection. |
| `DIRECT` | Traffic may expose the VPS public IP. |
| `UNKNOWN` | SnarkyCtl cannot verify the effective policy. |

`DIRECT` must always produce a conspicuous public-IP exposure warning. Intentional Direct
VPS mode requires a separate future implementation and explicit confirmation.

### 3.5 Fail visibly

Partial collector failures must not erase valid status from other components. Browser
responses contain controlled error codes and messages. Raw provider output and `stderr`
remain server-side.

### 3.6 Serialize mutations

The privileged daemon admits only one connect or disconnect operation at a time. A
competing mutation fails immediately with `OPERATION_IN_PROGRESS`; the web API maps this
to HTTP `409 Conflict`.

Status and target-catalogue reads remain available during a mutation. The operation lock
must be released after success, timeout, provider failure, or an unexpected exception.

## 4. Component Model

```text
Browser
   │ authenticated HTTPS
   ▼
Unprivileged web service
   │ typed versioned protocol
   ▼
Protected Unix socket
   │ verified peer credentials
   ▼
Privileged control daemon
   │ trusted adapter
   ▼
Configured VPN provider
```

### 4.1 Web service

The web service is responsible for:

- HTTP Basic authentication.
- Same-origin request protection.
- Strict request and response schemas.
- Serving the dashboard and same-origin assets.
- Sending typed requests to the control daemon.
- Mapping controlled daemon failures to HTTP status codes.

It does not execute provider commands, read private provider target values, alter routing,
or write root-owned configuration.

### 4.2 Control daemon

The root daemon is responsible for:

- Loading immutable validated configuration.
- Resolving public aliases to private provider targets.
- Enforcing provider capabilities.
- Serializing provider mutations.
- Executing the configured trusted adapter.
- Normalizing status and gateway mode.
- Returning only controlled protocol responses.

### 4.3 Provider adapters

Every adapter implements the same trusted interface:

- `status()`
- `settings()`
- `connect(target)`
- `disconnect()`
- Provider capabilities

The adapter owns provider-specific commands, parsing, timeouts, target validation, and
interpretation of leak-protection settings. SnarkyCtl does not manipulate routing tables
when the provider owns its routing.

## 5. Configuration

SnarkyCtl reads:

```text
/etc/snarkyctl/snarkyctl.yaml
/etc/snarkyctl/targets.yaml
/etc/snarkyctl/auth.htpasswd
```

Configuration is versioned, schema-validated, size-limited, and loaded with a safe YAML
parser. Provider names must exist in the compiled trusted registry. Configuration cannot
load executable code.

There is no application database. Passwords are not stored; the authentication file
contains a username and salted password hash in standard `htpasswd` format.

## 6. Provider-Neutral Target Catalogue

Each root-approved target contains:

```yaml
schema_version: 1

targets:
  - alias: dallas
    label: Dallas, United States
    provider_target: us

  - alias: prague
    label: Prague, Czechia
    provider_target: cz
```

- `alias` is the stable public identifier used by the browser, API, and CLI.
- `label` is presentation text.
- `provider_target` is private adapter input read only by the privileged daemon.

Aliases begin with a lowercase letter and contain only lowercase letters, digits,
underscores, and hyphens. Unknown aliases never reach the provider.

The browser-facing catalogue contains only:

- Provider name.
- Normalized provider capabilities.
- Target aliases.
- Target labels.

It must never contain `provider_target`.

## 7. VPN Target Switching

### 7.1 Dashboard behavior

The dashboard:

1. Retrieves `GET /api/v2/vpn/targets`.
2. Confirms that the provider advertises connect and target-selection capabilities.
3. Populates the selector from approved aliases and labels.
4. Retrieves current status from `GET /api/v2/status`.
5. Selects the current alias when it is known.
6. Sends the selected alias to `POST /api/v2/vpn/connect`.
7. Disables the controls while the request is running.
8. Displays controlled success or failure text.
9. Refreshes status after completion.

The selector must not default to the first target and thereby claim it is active. If the
current alias is unknown, it displays **Select a target…**.

The daemon remembers the last alias successfully selected through SnarkyCtl for its
process lifetime. This keeps polling and page reloads synchronized. The alias is
deliberately unknown after a daemon restart or when the provider was changed outside
SnarkyCtl; no persistent default is inferred.

### 7.2 Connect API

The request body is:

```json
{
  "target": "prague"
}
```

The web process validates the alias and sends only that alias through the Unix socket.
The daemon repeats the authoritative lookup and gives the adapter the configured private
provider value.

The connect endpoint rejects:

- Missing, malformed, or option-like aliases.
- Extra request fields.
- Unknown aliases.
- Raw provider server names or locations.
- Competing provider mutations.
- Cross-origin requests.

### 7.3 Connection sequence

The privileged sequence is:

1. Validate the protocol request.
2. Attempt to acquire the non-blocking operation lock.
3. Resolve the alias from the immutable root-owned catalogue.
4. Invoke the adapter with the corresponding provider target.
5. Query the provider's resulting status.
6. Normalize the response target back to the public alias.
7. Record that alias in daemon memory.
8. Release the operation lock in `finally`.

## 8. HTTP Security

All operational routes require HTTP Basic authentication over HTTPS. The liveness route is
the only intentionally unauthenticated endpoint.

Every state-changing request requires:

```http
Content-Type: application/json
X-SnarkyCtl-Request: 1
```

Browser requests must also be same-origin according to Fetch Metadata, and any supplied
`Origin` must exactly match the service origin. CORS is not enabled. These checks occur
before the privileged daemon is contacted.

The deployed service disables interactive API documentation and applies restrictive
security, framing, referrer, permissions, and no-store response headers.

## 9. Stable Errors

Errors use:

```json
{
  "error": {
    "code": "OPERATION_IN_PROGRESS",
    "message": "Another VPN control operation is already in progress."
  }
}
```

Important mappings include:

| HTTP status | Error |
|---|---|
| `400` | `INVALID_REQUEST` |
| `401` | `AUTHENTICATION_REQUIRED` |
| `403` | `CROSS_ORIGIN_REQUEST` |
| `404` | `UNKNOWN_TARGET` |
| `409` | `OPERATION_IN_PROGRESS` |
| `502` | Provider or daemon response failure |
| `504` | Provider or daemon timeout |

## 10. Packaging and Services

The deployment package contains:

- The Python application and dependencies in `/usr/lib/snarkyctl/venv`.
- Static dashboard assets and templates.
- The control socket, control daemon, and web systemd units.
- Example configuration.
- CLI commands.

Package installation must not connect or disconnect a VPN, modify routes or firewall
rules, create credentials, or enable services automatically.

The three systemd units are:

```text
snarkyctl-control.socket
snarkyctl-control.service
snarkyctl-web.service
```

## 11. Verification Requirements

Automated verification includes:

- Provider parsing and controlled command failures.
- Protocol validation and message-size limits.
- Root-authoritative alias resolution.
- Confirmation that private provider targets never reach browser responses.
- Successful target switching away from the first catalogue entry.
- Preservation of the current alias through status refreshes.
- Neutral selector behavior when the alias is unknown.
- Cross-origin and wrong-content-type rejection before daemon access.
- Concurrent mutation rejection with read availability.
- Lock release after successful and failed provider operations.
- Authentication and security headers.
- Configuration, preflight, packaging, and systemd-unit checks.
- A minimum 90% branch-coverage gate.

Operational acceptance must confirm:

- The HTTPS listener is private.
- Authentication is required.
- Provider transitions do not break the independent management path.
- Target switching changes the provider and dashboard selection consistently.
- Provider failure does not silently expose the VPS public IP.

## 12. Roadmap

### 12.1 Provider-neutral target administration

Add authenticated dashboard operations to create, edit, and remove targets.

Each installed adapter will publish declarative target-field metadata. The common
dashboard will render those fields without provider-specific JavaScript. The privileged
daemon will:

- Validate and normalize adapter-specific fields.
- Reject duplicates, unsafe lengths, option-like values, symlinks, and extra fields.
- Serialize catalogue changes against provider mutations.
- Write the root-owned catalogue atomically with safe ownership and permissions.
- Preserve a rollback copy.
- Reload the catalogue only after a successful write.

Ordinary connection requests will remain alias-only.

### 12.2 Additional trusted providers

Add trusted adapters for:

- Administrator-supplied OpenVPN-compatible configurations.
- Mullvad using a supported client or configuration mechanism.

Every adapter must provide normalized capabilities, status, settings, target validation,
connect, disconnect, timeouts, controlled errors, preflight checks, and parser fixtures.

Provider installation is not a browser upload feature. New executable code, command
paths, or plugins must arrive through a reviewed package or software upgrade. The UI may
select only among installed adapters in the trusted registry.

### 12.3 Later controls

Possible later additions include:

- Dashboard disconnection.
- Explicit Locked mode.
- Explicitly confirmed Direct VPS mode.
- Audit history for management actions.
- Latency tests for approved targets.
- Selection among installed trusted providers.
- Carefully reviewed service administration.

Each addition requires its own authorization, privilege-boundary, failure-mode, and
public-IP-exposure review.
