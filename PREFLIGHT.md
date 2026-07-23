# SnarkyCtl Preflight

`snarkyctl preflight` performs read-only deployment checks before the systemd services are activated. It does not connect or disconnect a VPN, modify firewall or routing state, change files, or start services.

Run the normal human-readable report as root so that certificate keys and root-owned configuration can be inspected:

```bash
sudo snarkyctl preflight
```

Automation can request a stable, versioned JSON document:

```bash
sudo snarkyctl preflight --json
```

An alternate main configuration can be selected with `--config PATH`.

## Result States

| State | Meaning |
|---|---|
| `PASS` | The required property was verified. |
| `WARN` | The deployment can continue, but the administrator should review the condition. |
| `FAIL` | A required safety or operational property was not verified. |
| `SKIP` | The check does not apply, cannot run in the current state, or is not implemented yet. |

Exit status `0` means that no check failed; warnings and skips may still be present. Exit status `1` means at least one check failed. Exit status `2` means configuration could not be loaded or validated, so the checks could not begin.

## Implemented Checks

The initial implementation verifies:

- Versioned main configuration and target allowlist.
- Existence of the `snarkyctl` user and group.
- Non-interactive service-account login shell and correct primary group.
- Root ownership and safe modes for configuration, authentication, certificate, and key files.
- Existence of the management and public interfaces.
- Assignment of the configured management IPv4 address to the management interface.
- Availability of the configured private HTTPS port.
- At least one syntactically valid bcrypt record in `auth.htpasswd`.
- Successful loading of the TLS certificate/private-key pair.
- Certificate validity and coverage of the configured private management IP address.
- Presence of the selected provider's initial external prerequisite.
- Required user, privilege, and socket directives in the installed systemd units.
- Type, owner, group, and mode of the live control socket when it is active.

The provider check is adapter-specific. The first NordVPN check confirms that its command-line executable is available. It does not contact the daemon or change connection state.

## Deliberate Limitations

Firewall-policy analysis is not implemented in this first version and appears as `SKIP`. That result must not be interpreted as proof that forwarding is fail-closed or that port `8443` is blocked on the public interface. Do not enable state-changing forwarding controls until the nftables inspection and Locked-mode transition layer are implemented and tested on a disposable gateway.

An inactive control socket also appears as `SKIP`; this is normal when preflight is run before first activation. Its installed systemd socket definition is still checked.

Preflight validates local machine properties only. Linode Cloud Firewall rules must be reviewed separately because they are outside the VPS operating system.
