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

## Administrative target catalogue API

The management editor uses three authenticated endpoints:

```text
GET /api/v3/admin/vpn/target-schema
GET /api/v3/admin/vpn/targets
PUT /api/v3/admin/vpn/targets
```

The schema endpoint returns the active compiled provider's data-only selector schema.
Reviewed field types are limited to `text`, `choice`, `boolean`, and `integer`. Provider
HTML or JavaScript is never returned or executed.

The administrative catalogue endpoint includes structured selectors and the current
revision. Unlike `GET /api/v2/vpn/targets`, it is intended only for authenticated
administration:

```json
{
  "provider": "nordvpn",
  "revision": 3,
  "targets": [
    {
      "alias": "dallas",
      "label": "Dallas",
      "position": 0,
      "selector": {
        "kind": "city",
        "country": "us",
        "city": "Dallas"
      }
    }
  ]
}
```

Replacement submits the complete catalogue with `provider`, `expected_revision`, and a
nonempty `targets` array. It requires `Content-Type: application/json` and
`X-SnarkyCtl-Request: 1`; the same Fetch Metadata and exact-origin checks used by other
state-changing endpoints apply.

A stale revision returns HTTP 409 with `CATALOG_CONFLICT`; the client must reload rather
than overwrite. Provider validation failures return HTTP 400, unsupported selection
returns HTTP 409, and daemon or storage failures return HTTP 502.

The web process does not open SQLite. It forwards bounded typed requests through the Unix
socket, and the daemon updates its active snapshot only after the database transaction
commits. Ordinary API responses continue omitting selectors.

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
private structured selector to the configured adapter. Arbitrary provider values, command
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
browser requests cannot pass the required request-marker, Fetch Metadata, and Origin
checks. SnarkyCtl does not enable CORS.

The privileged daemon serializes connect and disconnect operations with one non-blocking
operation lock. Read-only status and target-catalogue requests remain available while a
mutation runs. A competing mutation fails immediately instead of waiting behind the
provider command.

## Gateway mode operations

The dashboard places the following policy operations inside a collapsed **Advanced
gateway modes — Danger zone** section. They are available only when the active adapter
advertises leak-protection configuration support:

| Endpoint | Request body | Ordered daemon actions | Required result |
|---|---|---|---|
| `POST /api/v2/mode/protected` | `{"target":"dallas"}` | Enable protection, connect to the approved alias | `VPN` |
| `POST /api/v2/mode/locked` | `{}` | Enable protection, disconnect the VPN | `LOCKED` |
| `POST /api/v2/mode/direct` | `{"confirmation":"EXPOSE VPS IP"}` | Disable protection, disconnect the VPN | `DIRECT` |

All three endpoints require Basic authentication, JSON, the
`X-SnarkyCtl-Request: 1` marker, and the same browser-origin checks described above.
The protected endpoint accepts an alias only; its provider target remains root-owned.
Requests without `Content-Type: application/json` receive HTTP `415` with
`INVALID_CONTENT_TYPE`.

Direct VPS mode exposes the VPS public IP. The API schema accepts only the exact
confirmation phrase `EXPOSE VPS IP`, and the dashboard keeps its Direct button disabled
until that phrase is entered. If the disconnect or final-state verification fails after
protection is disabled, the daemon attempts to restore leak protection before returning
the provider error.

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
