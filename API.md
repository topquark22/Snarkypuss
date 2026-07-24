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

## Read-only dashboard

The authenticated `/` route serves the initial status dashboard. Its HTML contains no
state-changing controls and no inline scripts or styles. A small same-origin JavaScript
client polls `GET /api/v2/status` every five seconds.

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
`partial_failures` contains bounded component errors. A component failure leaves its
corresponding object `null`; the endpoint still returns HTTP 200 when a valid partial
snapshot is available. A missing VPN component produces an indeterminate exposure state,
never a false assertion that the public IP is protected.

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
