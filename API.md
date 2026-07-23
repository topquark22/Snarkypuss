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

## `GET /api/health/live`

Returns the web process name and package version. This endpoint does not query the control
daemon.

## `GET /api/v1/status`

Returns provider-neutral upstream VPN and gateway status. Example:

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
