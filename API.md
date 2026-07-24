# HTTP API

SnarkyCtl's HTTPS API runs as the unprivileged `snarkyctl` Linux user. It does not
invoke a VPN application, manipulate routing, or perform privileged operations. Status
requests are sent through `/run/snarkyctl/control.sock` to the privileged control daemon.

## Authentication

All operational endpoints use HTTP Basic authentication over HTTPS. Credentials are
verified against the bcrypt records in `/etc/snarkyctl/auth.htpasswd`. SnarkyCtl stores
neither plaintext passwords nor sessions in a database.

The process-liveness endpoint is intentionally unauthenticated so that systemd and local
monitoring can determine whether the web process is running. It contains no gateway data.

## Browser hardening

FastAPI's interactive `/docs` and `/redoc` pages and its `/openapi.json` schema route are
disabled. The deployed service does not expose implementation discovery pages.

Every HTTP response, including authentication and daemon errors, carries:

- A restrictive Content Security Policy permitting resources and API connections only
  from the same origin, while prohibiting objects, embedding, and base-URL changes.
- `Strict-Transport-Security` with a one-year lifetime.
- `X-Content-Type-Options: nosniff`.
- Both CSP `frame-ancestors 'none'` and `X-Frame-Options: DENY`.
- `Referrer-Policy: no-referrer`.
- A Permissions Policy disabling camera, microphone, and geolocation.
- `Cache-Control: no-store`.

Dashboard scripts and styles must therefore be served as separate same-origin static files.
Inline scripts and inline styles are not permitted.

## Dashboard

The authenticated `/` route serves the status and VPN-target dashboard. It contains no
inline scripts or styles. A small same-origin JavaScript client polls
`GET /api/v2/status` every five seconds.

The target selector is populated from `GET /api/v2/vpn/targets` and is enabled only when
the provider advertises both connect and target-selection capabilities. Selecting
**Connect / switch** sends only the chosen public alias to `POST /api/v2/vpn/connect`.
Provider command arguments and other provider-specific target details remain in the
privileged service and are never sent to the browser. The control is disabled while a
request is in progress and reports success or sanitized API errors in place.

The dashboard gives the gateway mode visual priority. `DIRECT` mode uses a red state panel
and a separate public-IP exposure alert. `UNKNOWN` and communication failures warn that
gateway safety cannot be confirmed. `VPN` and `LOCKED` are displayed as non-exposing
states. Provider, target, server, interface, VPN state, leak protection, and refresh time
appear in the connection details panel.

DNS service state and local VPS health appear in separate read-only cards. If one collector
fails, the dashboard keeps the available components visible and lists the incomplete
component without treating the entire gateway as unavailable.

## `GET /api/health/live`

Returns the web process name and package version. This endpoint does not query the control
daemon.

## `GET /api/v1/status`

Returns the original provider-neutral upstream VPN and gateway status for compatibility.
New clients should use `/api/v2/status`. Example:

```json
{
  "version": 1,
  "vpn_status": {
    "state": "CONNECTED",
    "provider": "nordvpn",
    "gateway_mode": "VPN",
    "leak_protection_active": true,
    "target": "dallas",
    "display_name": null,
    "interface": "nordlynx",
    "connected_since": null,
    "diagnostic_code": null,
    "details": {}
  },
  "public_ip_exposed": false,
  "exposure_warning": null
}
```

When `gateway_mode` is `DIRECT`, `public_ip_exposed` is `true` and
`exposure_warning` explicitly states that the VPS real public IP address is exposed.
When the mode is `UNKNOWN`, exposure is `null` and the warning says that exposure cannot
be determined.

## `GET /api/v2/status`

Returns the complete, partially degradable local gateway snapshot:

```json
{
  "version": 2,
  "checked_at": "2026-07-24T15:30:00Z",
  "vpn_status": {
    "state": "CONNECTED",
    "provider": "nordvpn",
    "gateway_mode": "VPN",
    "leak_protection_active": true,
    "target": "dallas",
    "display_name": "United States #6275",
    "interface": "nordlynx",
    "connected_since": null,
    "diagnostic_code": null,
    "details": {}
  },
  "public_ip": {
    "address": "203.0.113.42",
    "version": 4,
    "checked_at": "2026-07-24T15:30:00Z"
  },
  "dns": {
    "service": "dnsmasq.service",
    "load_state": "loaded",
    "active_state": "active",
    "sub_state": "running"
  },
  "system": {
    "uptime_seconds": 183642,
    "load_average": [0.08, 0.11, 0.09],
    "memory_total_bytes": 2097152000,
    "memory_available_bytes": 1325400064,
    "root_disk_total_bytes": 53687091200,
    "root_disk_free_bytes": 41775267840
  },
  "partial_failures": [],
  "public_ip_exposed": false,
  "exposure_warning": null
}
```

The daemon gathers `dnsmasq.service` state and host health without changing either.
It queries the root-configured public-IP endpoint only when the gateway mode is confirmed
as `VPN` or `DIRECT`. The request uses HTTPS certificate and hostname verification,
does not follow redirects, accepts only a bounded plain-text IPv4 response, and is skipped
in `LOCKED` or indeterminate modes.

`partial_failures` contains bounded component errors. A component failure leaves its
corresponding object `null`; the endpoint still returns HTTP 200 when a valid partial
snapshot is available. A missing VPN component produces an indeterminate exposure state,
never a false assertion that the public IP is protected.

## `GET /api/v2/vpn/targets`

Returns the provider-neutral capabilities and root-approved connection targets for the
configured upstream VPN:

```json
{
  "version": 2,
  "provider": "nordvpn",
  "capabilities": {
    "connect": true,
    "disconnect": true,
    "target_selection": true,
    "server_details": true
  },
  "targets": [
    {
      "alias": "dallas",
      "label": "Dallas, United States"
    },
    {
      "alias": "prague",
      "label": "Prague, Czechia"
    }
  ]
}
```

The web process obtains this catalogue from the privileged daemon. It does not read or
return the provider-specific target value. Consequently, neither the browser nor this API
can discover that an alias maps to a NordVPN country code, server name, or another
provider's private command argument.

The capabilities allow future dashboard controls to adapt to the configured provider
without embedding provider names or assumptions in JavaScript. This endpoint is
authenticated and read-only; it does not connect or disconnect the VPN.

## `POST /api/v2/vpn/connect`

Requests a connection using one provider-neutral alias from the root-owned target
catalogue:

```json
{
  "target": "dallas"
}
```

The web service validates the request schema and sends only the alias through the Unix
socket. The privileged daemon performs the authoritative lookup and passes the associated
private `provider_target` to the configured adapter. Arbitrary provider values, command
options, executable names, and extra request fields are rejected.

Every state-changing request must include:

```http
X-SnarkyCtl-Request: 1
```

This non-simple header forces a cross-origin browser to perform a CORS preflight, which
SnarkyCtl does not permit. Browser requests are also rejected unless `Sec-Fetch-Site`
identifies them as same-origin and any supplied `Origin` exactly matches the service
origin. Non-browser API clients may omit `Origin` and `Sec-Fetch-Site`, but must still
send the request marker. These checks are applied after Basic authentication and before
the privileged daemon is contacted.

A successful response contains normalized provider status:

```json
{
  "version": 2,
  "message": "Connected using target alias dallas.",
  "vpn_status": {
    "state": "CONNECTED",
    "provider": "nordvpn",
    "gateway_mode": "VPN",
    "leak_protection_active": true,
    "target": "dallas",
    "display_name": "United States #6275",
    "interface": "nordlynx",
    "connected_since": null,
    "diagnostic_code": null,
    "details": {}
  },
  "public_ip_exposed": false,
  "exposure_warning": null
}
```

The endpoint returns:

- HTTP 400 with `INVALID_REQUEST` for a malformed body or alias.
- HTTP 401 for missing or invalid Basic authentication.
- HTTP 403 with `CROSS_ORIGIN_REQUEST` for a missing request marker or an origin mismatch.
- HTTP 404 with `UNKNOWN_TARGET` when the alias is not root-approved.
- HTTP 409 with `OPERATION_IN_PROGRESS` when another VPN mutation holds the daemon's
  operation lock.
- HTTP 502 for provider failures or invalid daemon responses.
- HTTP 504 for provider or control-daemon timeouts.

This endpoint does not accept raw NordVPN country codes or server names. Cross-origin
request protection for browser use is added separately before dashboard controls are
enabled.

Errors use one stable envelope:

```json
{
  "error": {
    "code": "DAEMON_UNAVAILABLE",
    "message": "control daemon is not accepting connections"
  }
}
```

Authentication failures return HTTP 401. Configuration or auth-file failures return HTTP
503. A missing, unreachable, or invalid control-daemon response returns HTTP 502.
