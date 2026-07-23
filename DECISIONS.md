# SnarkyCtl Architecture Decisions

This document records decisions that constrain the first implementation. They are requirements-baseline decisions rather than incidental implementation details.

## ADR-001: Native Debian deployment package

**Decision:** The deployable artifact is an Ubuntu/Debian `.deb`. The Python application is first built as a wheel, and the `.deb` contains a preassembled virtual environment.

**Consequences:** Installation does not contact PyPI. The first target is Ubuntu 24.04 `amd64`. Application dependencies are locked and assembled during the build.

## ADR-002: Two-service privilege separation

**Decision:** SnarkyCtl consists of two system services:

- `snarkyctl-web.service` runs as the unprivileged `snarkyctl` account and serves HTTPS.
- `snarkyctl-control.service` runs as root and performs a small, fixed set of privileged network operations.
- `snarkyctl-control.socket` provides a root-owned Unix-domain socket at `/run/snarkyctl/control.sock`, accessible only to root and the `snarkyctl` group.

The web service never invokes `sudo` and is not a member of a broadly privileged networking group.

**Rationale:** This allows `NoNewPrivileges=true` and strong sandboxing on the network-facing web service. It also prevents a web-process compromise from turning arbitrary command arguments into root shell execution.

**Consequences:** The control protocol, peer verification, socket permissions, service ordering, and failure behaviour are part of the first implementation rather than a later retrofit.

## ADR-003: Minimal privileged control protocol

**Decision:** The control daemon accepts only versioned, schema-validated operations such as:

```text
STATUS
LOCK
CONNECT <approved-alias>
DISCONNECT
DIRECT <confirmation-token>
```

The precise wire representation may be length-delimited JSON, but it must have a size limit, protocol version, request identifier, fixed operation enumeration, strict field validation, bounded execution time, and structured response.

The daemon verifies the connecting process through Unix-socket permissions and Linux peer credentials. It accepts requests only from root or the configured `snarkyctl` UID. It never accepts shell text, executable paths, firewall fragments, filenames, or arbitrary provider targets.

## ADR-004: Firewall-enforced fail-closed modes

**Decision:** Locked behaviour is enforced by firewall and forwarding policy, not by periodic health monitoring alone.

- In VPN mode, forwarded client traffic is permitted only through the verified interface reported by the configured provider.
- If that interface disappears, the forwarding rule no longer matches and traffic is blocked without waiting for the web service or control daemon to react.
- Direct VPS mode has a separate, explicit public-interface forwarding rule.
- Locked mode permits neither forwarding path.
- WireGuard management traffic remains permitted in every mode.

All mode changes are performed atomically by the root control daemon. On boot, the firewall policy starts Locked. Direct VPS mode is never restored automatically.

## ADR-005: Explicit public-interface configuration

**Decision:** The VPS public interface is explicitly named in root-owned configuration and validated against the live system during preflight. It is not silently guessed when changing modes.

## ADR-006: HTTP Basic authentication without a database

**Decision:** The HTTPS service uses HTTP Basic authentication backed by `/etc/snarkyctl/auth.htpasswd`.

There is no user database, login page, cookie session, or server-side session store. The file contains a salted password hash rather than the plaintext password.

State-changing requests also require same-origin JSON requests and a dedicated request header. CORS is not enabled.

## ADR-007: Direct TLS termination in Uvicorn

**Decision:** Uvicorn terminates HTTPS directly for the first release. The service loads `/etc/snarkyctl/tls/server.crt` and `/etc/snarkyctl/tls/server.key` and binds only to `10.8.0.1:8443`.

There is no nginx or Apache reverse proxy in the first deployment.

## ADR-008: No database

**Decision:** SnarkyCtl uses files for configuration, authentication, certificates, and minimal state. It does not use a relational database, Redis, or another state service.

If persistent mode policy is necessary, it is stored in a small versioned file written atomically under `/var/lib/snarkyctl`. Direct VPS mode is not restored automatically after reboot.

## ADR-009: Canonical names and paths

**Decision:** The application, package, command, Linux service account, and configuration namespace are all named `snarkyctl`.

Canonical installed paths include:

```text
/usr/lib/snarkyctl/
/etc/snarkyctl/
/run/snarkyctl/
/var/lib/snarkyctl/
```

The live WireGuard gateway, currently configured with NordVPN as its upstream provider, remains named `snarkypuss`.

## ADR-010: Initial activation requires preflight

**Decision:** Package installation does not automatically enable a partially configured service. `snarkyctl preflight` must validate networking, configuration, authentication, TLS, control-socket permissions, service ownership, and Locked-mode safety before activation.

## ADR-011: Requirements-baseline tag

**Decision:** The first documentation tag represents a requirements and architecture baseline, not a working application release. Application release versions begin only after buildable code and packaging exist.


## ADR-012: Provider-neutral upstream VPN boundary

**Decision:** Core policy, protocol, API, status models, and firewall logic refer to an optional upstream VPN rather than NordVPN.

A fixed compiled registry selects a trusted `VpnProvider` adapter. Configuration may choose a registered provider name but may not load an arbitrary Python module. The first built-in implementation is `NordVpnProvider`; generic WireGuard and OpenVPN adapters may be added later.

Provider adapters own provider-specific command execution and parsing. They return common status models and a verified upstream interface. They do not construct firewall rules. The provider-neutral firewall layer implements VPN, Direct VPS, and Locked modes.

The distributed systemd units have no hard dependency on `nordvpnd.service`. Provider-specific service ordering may be added through an administrator-controlled systemd drop-in.
