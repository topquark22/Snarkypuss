# SnarkyCtl HTTP API Reference

## Purpose

SnarkyCtl exposes a private HTTPS API used by the dashboard and available to other trusted
clients on the WireGuard management network.

The API is provider-neutral. Browser and API clients work with SnarkyCtl target aliases and
gateway modes; they do not submit arbitrary provider commands or executable paths.

The HTTPS application runs as the unprivileged `snarkyctl` Linux user. Privileged operations
are forwarded through `/run/snarkyctl/control.sock` to the control daemon.

## 1. Access and authentication

The reference service listens at:

```text
https://10.8.0.1:8443/
```

or, when the private hostname is configured:

```text
https://snarkypuss:8443/
```

The API is intended to be reachable only through the private WireGuard management network.
Do not expose it on the VPS public interface.

All operational endpoints require HTTP Basic authentication over HTTPS. Credentials are
verified against the configured `auth.htpasswd` file.

The exception is:

```text
GET /api/health/live
```

which is intentionally unauthenticated and returns only web-process liveness information.

SnarkyCtl does not expose FastAPI `/docs`, `/redoc`, or `/openapi.json` routes in production.

## 2. Common response security headers

Every response includes the service security headers, including:

```text
Cache-Control: no-store
Strict-Transport-Security: max-age=31536000
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
```

The Content Security Policy restricts scripts, styles, images, and API connections to the
same origin and forbids framing and object embedding.

## 3. State-changing request requirements

All state-changing API requests require:

```http
Content-Type: application/json
X-SnarkyCtl-Request: 1
```

Browser requests must also be same-origin. If `Sec-Fetch-Site` is supplied, it must be
`same-origin`. If `Origin` is supplied, it must exactly match the SnarkyCtl service origin.

SnarkyCtl does not enable CORS.

A missing request marker or origin mismatch returns HTTP `403` with
`CROSS_ORIGIN_REQUEST`. A state-changing request with a non-JSON content type returns HTTP
`415` with `INVALID_CONTENT_TYPE`.

These checks occur before the privileged control daemon is contacted.

## 4. Error envelope

Controlled API errors use one stable JSON envelope:

```json
{
  "error": {
    "code": "DAEMON_UNAVAILABLE",
    "message": "control daemon is not accepting connections"
  }
}
```

Common HTTP statuses include:

| Status | Typical meaning |
|---|---|
| `400` | Invalid request body, selector, or catalogue |
| `401` | Authentication required or credentials invalid |
| `403` | State-changing request failed same-origin protection |
| `404` | Unknown target or provider |
| `409` | Operation already in progress, unsupported operation, or catalogue conflict |
| `415` | State-changing request is not JSON |
| `502` | Provider/control failure or invalid daemon response |
| `503` | SnarkyCtl configuration or authentication source unavailable |
| `504` | Provider or control-daemon timeout |

Request-schema failures return HTTP `400` with:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "request body does not match the API schema"
  }
}
```

Error `code` values are intended to be more stable for clients than free-form message text.

## 5. `GET /api/health/live`

Reports only that the HTTPS web process is running.

Authentication is not required.

Example response:

```json
{
  "status": "ok",
  "service": "snarkyctl-web",
  "version": "0.10.0.dev4"
}
```

This endpoint does not query the control daemon and does not report VPN, DNS, gateway, or
system state.

## 6. `GET /api/v1/status`

This is the original compatibility status endpoint. New clients should use
`GET /api/v2/status`.

Authentication is required.

Example response:

```json
{
  "version": 1,
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

`public_ip_exposed` is:

- `false` for `VPN` and `LOCKED`,
- `true` for `DIRECT`, and
- `null` for `UNKNOWN`.

When exposure is true or indeterminate, `exposure_warning` contains a corresponding warning.

## 7. `GET /api/v2/status`

Returns the current provider-neutral gateway snapshot.

Authentication is required.

Example:

```json
{
  "version": 2,
  "checked_at": "2026-09-15T03:00:00Z",
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
  "public_ip": {
    "address": "203.0.113.42",
    "version": 4,
    "checked_at": "2026-09-15T03:00:00Z"
  },
  "partial_failures": [],
  "public_ip_exposed": false,
  "exposure_warning": null
}
```

The snapshot is intentionally partially degradable. If DNS, system, public-IP, or another
collector fails, its corresponding object may be `null` and the failure appears in
`partial_failures` while the endpoint still returns a usable snapshot.

A partial failure has this shape:

```json
{
  "component": "dns",
  "code": "DNS_STATUS_FAILED",
  "message": "dnsmasq status query failed"
}
```

The public-IP lookup is performed only when the gateway mode is confirmed as `VPN` or
`DIRECT`. It is skipped in `LOCKED` or indeterminate states.

## 8. `GET /api/v2/vpn/targets`

Returns the active provider's public target catalogue and capabilities.

Authentication is required.

Example:

```json
{
  "version": 2,
  "provider": "nordvpn",
  "capabilities": {
    "connect": true,
    "disconnect": true,
    "target_selection": true,
    "server_details": true,
    "leak_protection_configuration": true
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

This endpoint deliberately omits provider-specific selector documents. Ordinary clients see
only aliases, labels, the active provider identifier, and provider capabilities.

## 9. `POST /api/v2/vpn/connect`

Connects the active provider using one approved target alias.

Authentication and the state-changing request requirements from Section 3 apply.

Request:

```json
{
  "target": "dallas"
}
```

The alias is resolved by the privileged service against the approved target catalogue. The
client cannot use this endpoint to submit a raw NordVPN server name, country code, executable
path, or shell argument.

Example success response:

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

Important errors include:

- `UNKNOWN_TARGET` — alias is not in the approved catalogue (`404`),
- `OPERATION_IN_PROGRESS` — another VPN mutation already holds the operation lock (`409`),
- `PROVIDER_TIMEOUT` — provider command timed out (`504`), and
- `DAEMON_TIMEOUT` — control operation timed out (`504`).

Read-only status and target requests remain available while a mutation is running.

## 10. Gateway mode operations

SnarkyCtl exposes three higher-level gateway-policy operations.

### `POST /api/v2/mode/protected`

Enables provider leak protection and then connects to an approved target.

Request:

```json
{
  "target": "dallas"
}
```

The required resulting gateway mode is `VPN`.

### `POST /api/v2/mode/locked`

Enables provider leak protection and disconnects the upstream VPN.

Request body:

```json
{}
```

The required resulting gateway mode is `LOCKED`.

### `POST /api/v2/mode/direct`

Disables provider leak protection and disconnects the upstream VPN, intentionally allowing
client traffic to use the VPS public connection.

Request:

```json
{
  "confirmation": "EXPOSE VPS IP"
}
```

The confirmation string is exact. The required resulting gateway mode is `DIRECT`.

If a Direct transition fails after leak protection has been disabled, the privileged daemon
attempts to restore leak protection before reporting the failure.

All three endpoints require authentication, JSON, `X-SnarkyCtl-Request: 1`, and the browser
same-origin protections described earlier.

These operations are available only when the active provider adapter supports leak-protection
configuration.

## 11. Administrative target catalogue API

The destination editor uses three authenticated v3 endpoints:

```text
GET /api/v3/admin/vpn/target-schema
GET /api/v3/admin/vpn/targets
PUT /api/v3/admin/vpn/targets
```

These endpoints are administrative because they expose or modify provider-specific selector
data that the ordinary v2 target API intentionally hides.

### `GET /api/v3/admin/vpn/target-schema`

Returns reviewed, data-only schema metadata for the active compiled provider.

A provider schema contains selector kinds and fields. Currently supported field types are:

```text
text
choice
boolean
integer
```

The endpoint does not return provider-supplied HTML, JavaScript, executable code, or shell
commands.

### `GET /api/v3/admin/vpn/targets`

Returns the editable provider catalogue including structured selectors.

Example:

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

The `revision` value is used for optimistic concurrency.

### `PUT /api/v3/admin/vpn/targets`

Atomically replaces the active provider's complete catalogue.

Authentication and all state-changing request requirements apply.

Example request:

```json
{
  "provider": "nordvpn",
  "expected_revision": 3,
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

The replacement request currently requires at least one target and accepts at most 100.

If the stored revision no longer matches `expected_revision`, SnarkyCtl returns HTTP `409`
with `CATALOG_CONFLICT`. The client must reload the current catalogue instead of overwriting
it blindly.

Other catalogue errors include:

- `INVALID_CATALOG` (`400`),
- `UNKNOWN_PROVIDER` (`404`),
- `UNSUPPORTED_TARGET_SELECTION` (`409`), and
- `CATALOG_MIGRATION_REQUIRED` (`409`).

The web process does not open the SQLite database directly. Catalogue operations pass through
the control daemon and the active snapshot is updated only after the database transaction
commits.

## 12. API versions

SnarkyCtl currently exposes three API generations for different purposes:

| Version | Purpose |
|---|---|
| `v1` | Compatibility status endpoint |
| `v2` | Ordinary status, target selection, connection, and gateway-mode operations |
| `v3` | Administrative structured target-catalogue operations |

The version number describes the HTTP contract, not the upstream VPN provider.

New ordinary clients should use v2 endpoints rather than `/api/v1/status`.

The v3 namespace is not a replacement for every v2 endpoint. It exists because editable
provider selectors contain administrative information that the ordinary v2 catalogue
intentionally does not expose.

## 13. Trust boundary

The HTTP API is deliberately narrower than the privileged control daemon.

The browser and external API clients:

- authenticate to the unprivileged HTTPS process,
- use provider-neutral target aliases for ordinary connections,
- cannot execute provider commands directly,
- cannot submit arbitrary shell fragments or executable paths, and
- cannot open the root-controlled SQLite target database through the web process.

The HTTPS process validates the HTTP request, applies authentication and same-origin policy,
and sends a typed request over the local Unix socket. The privileged daemon performs the
trusted target lookup, provider validation, and network/provider operation.

The detailed privilege separation and control protocol are described in the architecture
reference later in this documentation series.
