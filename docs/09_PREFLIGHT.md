# SnarkyCtl Preflight Reference

## Purpose

`snarkyctl preflight` performs read-only checks of a SnarkyCtl installation before the web
service is activated or trusted.

It verifies local configuration, files, interfaces, credentials, TLS material, provider
prerequisites, and installed systemd definitions. It does not connect or disconnect the VPN,
change provider settings, alter routing or firewall state, modify files, or start services.

Preflight is a deployment sanity check. A successful report means that the properties it
checks were verified; it is not an end-to-end proof that client traffic is protected.

## 1. Run preflight

Run the normal report as root:

```bash
sudo snarkyctl preflight
```

The default configuration file is:

```text
/etc/snarkyctl/snarkyctl.yaml
```

To use another configuration file:

```bash
sudo snarkyctl preflight --config /path/to/snarkyctl.yaml
```

For machine-readable output:

```bash
sudo snarkyctl preflight --json
```

Run preflight before first service activation and after material installation or configuration
changes when you want to re-check the deployment.

The configured SnarkyCtl HTTPS port is tested by attempting to bind it. If the web service is
already running on that port, the port-availability check will fail. Preflight is therefore
most useful before `snarkyctl-web.service` is started, or while that service is stopped.

## 2. Result states

Each check has one of four states:

| State | Meaning |
|---|---|
| `PASS` | The required property was verified. |
| `WARN` | The condition is not fatal, but the administrator should review it. |
| `FAIL` | A required safety or operational property was not verified. |
| `SKIP` | The check does not apply or cannot be performed in the current state. |

`WARN` is part of the stable result model even though the current implementation may not emit
one during an ordinary reference-deployment run.

A `SKIP` is not the same as a `PASS`. It means SnarkyCtl did not verify that property.

## 3. Exit status

The command uses these exit codes:

| Exit status | Meaning |
|---|---|
| `0` | No check returned `FAIL`. `WARN` or `SKIP` results may still be present. |
| `1` | At least one check returned `FAIL`. |
| `2` | The configuration could not be loaded or validated, so preflight could not begin. |

This makes the command suitable for installation scripts and other administrative automation.

## 4. Human-readable output

The normal report prints one line per check, for example:

```text
PASS  config.schema: configuration schema version 1 is valid
PASS  identity.user: user snarkyctl exists
PASS  network.management_interface: interface wg0 exists
PASS  tls.key_pair: certificate and private key match
SKIP  exposure.policy: public-IP exposure observation is not implemented; review provider configuration
```

Check identifiers are intended to remain stable enough for diagnosis and automation. The
human-readable message provides the observed detail.

## 5. JSON output

`--json` returns a versioned document of this form:

```json
{
  "schema_version": 1,
  "checks": [
    {
      "check_id": "config.schema",
      "status": "PASS",
      "message": "configuration schema version 1 is valid"
    }
  ]
}
```

Automation should use `check_id`, `status`, and `schema_version` rather than parsing the
human-readable terminal format.

## 6. Configuration check

Preflight begins by loading the configured SnarkyCtl YAML document through the normal
configuration validator.

If configuration loading or validation fails, preflight does not continue and the command
returns exit status `2`.

A successful load produces:

```text
config.schema
```

with `PASS` for the currently supported configuration schema.

Configuration structure and field meanings are documented in
[08_CONFIGURATION.md](08_CONFIGURATION.md).

## 7. Service-account checks

Preflight verifies the local `snarkyctl` service identity.

Current checks include:

```text
identity.user
identity.login_shell
identity.group
```

They verify that:

- the `snarkyctl` user exists,
- its login shell is non-interactive,
- the `snarkyctl` group exists, and
- the user's primary group is `snarkyctl`.

These checks concern the unprivileged web-service account. The separate control daemon runs
with the privileges required for gateway administration.

## 8. File ownership and permission checks

Preflight inspects the files selected by the active configuration and rejects symbolic links
or non-regular files where ordinary files are required.

It checks the main configuration, target storage, authentication file, TLS certificate, and
TLS private key.

For the current SQLite deployment, important expectations include:

- the main configuration is root-owned and is not writable by group or others;
- the target database is root-owned and is not readable by group or others;
- `auth.htpasswd` is root-owned and has the expected `snarkyctl` group;
- the TLS certificate is root-owned and may be publicly readable;
- the TLS private key is root-owned, has the expected `snarkyctl` group, and is not readable
  by others.

The exact paths come from `snarkyctl.yaml`.

The target database is checked as root-controlled state because the privileged control daemon,
not the network-facing web process, opens it in production.

## 9. Network checks

Preflight verifies the configured local network boundary.

Current check identifiers include:

```text
network.management_interface
network.public_interface
network.management_address
network.web_port
```

The checks verify that:

- the configured management interface exists;
- the configured public interface exists;
- the configured management IPv4 address is assigned to the management interface; and
- the configured private HTTPS address and port are available for the web service to bind.

These are local host checks. They do not test connectivity from the Windows client and do not
inspect the Linode Cloud Firewall.

## 10. Authentication check

The authentication check is:

```text
auth.syntax
```

It verifies that `auth.htpasswd` is readable and contains at least one syntactically valid
bcrypt record.

It does not know or test the user's plaintext password.

## 11. TLS checks

Preflight loads the configured certificate and private key as a TLS server pair and verifies
basic certificate properties.

Current check identifiers include:

```text
tls.key_pair
tls.validity
tls.management_address
```

They verify that:

- the certificate and private key can be loaded together;
- the certificate has not expired; and
- the certificate contains the configured private management IP address in its Subject
  Alternative Name entries.

These checks do not replace normal browser certificate validation from the Windows client.

## 12. Provider checks

Provider checks are adapter-specific.

If the selected provider has no implemented preflight support, preflight reports:

```text
provider.prerequisites    SKIP
```

rather than pretending the provider has been verified.

### NordVPN

For the current NordVPN reference provider, preflight verifies:

```text
provider.executable
provider.leak_protection
provider.firewall
```

It confirms that the fixed NordVPN executable is runnable at:

```text
/usr/bin/nordvpn
```

and queries the provider through the NordVPN adapter using read-only settings operations.

The current checks require SnarkyCtl to verify that:

- the NordVPN Kill Switch is enabled; and
- the NordVPN firewall is enabled.

If provider settings cannot be read or interpreted safely, the relevant check fails.

Preflight does not connect, disconnect, select a server, or change NordVPN settings.

Provider installation and policy are documented in [07_NORDVPN.md](07_NORDVPN.md).

## 13. systemd unit checks

Preflight inspects the installed SnarkyCtl unit files under `/usr/lib/systemd/system`.

Current checks are:

```text
systemd.web
systemd.control
systemd.socket
```

It confirms required security and identity directives, including:

- `snarkyctl-web.service` runs as user/group `snarkyctl` and uses `NoNewPrivileges=true`;
- `snarkyctl-control.service` runs as `root:root` and uses `NoNewPrivileges=true`; and
- `snarkyctl-control.socket` uses `/run/snarkyctl/control.sock`, owner `root`, group
  `snarkyctl`, and mode `0660`.

The detailed privilege separation and service architecture are documented in the architecture
reference later in this series.

## 14. Live control-socket check

If `/run/snarkyctl/control.sock` exists, preflight verifies that it is actually a Unix socket
with the expected ownership and mode.

The check identifier is:

```text
control.socket_live
```

A safe active socket produces `PASS`.

If the socket is not active, the result is `SKIP`. That is normal when preflight is run before
first service activation; the installed socket unit is still checked separately.

## 15. Exposure-policy check

The current implementation reports:

```text
exposure.policy    SKIP
```

with a message stating that public-IP exposure observation is not implemented by preflight.

This does **not** mean that Protected VPN, Locked, or Direct VPS modes are unavailable. Those
modes are implemented elsewhere in SnarkyCtl.

It means only that `snarkyctl preflight` does not perform an end-to-end observation proving
which public path forwarded client traffic would take.

## 16. What preflight does not prove

A completely passing preflight report does not by itself prove that:

- the Windows WireGuard client can reach the VPS;
- WireGuard is passing traffic in both directions;
- DNS works from the Windows client;
- the dashboard is reachable from Windows;
- forwarded Internet traffic exits through the intended VPN server;
- provider failure is fail-closed for real forwarded client traffic;
- Direct VPS mode exposes exactly the path expected;
- the Linode Cloud Firewall has the intended rules; or
- all services survive a reboot correctly.

Those properties require the setup acceptance tests, operational checks, and where appropriate
the fail-closed test described elsewhere in the numbered documentation.

In particular, do not interpret a successful preflight report as a substitute for the
fail-closed forwarding test.

## 17. When to run preflight

Useful times to run it include:

- after installing SnarkyCtl and before first activation;
- after changing `snarkyctl.yaml`;
- after replacing authentication or TLS material;
- after changing the upstream VPN provider installation or safety settings;
- after reinstalling or modifying SnarkyCtl systemd units; and
- during recovery or migration before returning the gateway to service.

When the web service is already active, remember that the HTTPS port-availability check is
expected to fail because the service itself owns the configured port. For a clean deployment
preflight, stop the web service first or run the check before starting it.
