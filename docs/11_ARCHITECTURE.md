# Snarkypuss Architecture

## Purpose

This document describes the architecture of **Snarkypuss as a complete system**: the private
client-to-VPS gateway, DNS and forwarding path, upstream VPN provider, and the SnarkyCtl
management plane that observes and controls the gateway.

The central architectural question is not which Python libraries are used. It is:

> Which component owns each kind of state, which components are trusted to change it, and how
> do data and control cross those trust boundaries?

The reference deployment is Windows 11 -> WireGuard -> Ubuntu VPS -> upstream VPN -> Internet.
NordVPN is the current compiled upstream provider, but the SnarkyCtl control architecture is
provider-neutral.

## 1. System overview

```text
Windows 11 client
       |
       | WireGuard private tunnel
       | 10.8.0.0/24
       v
+-------------------------- Snarkypuss VPS ---------------------------+
|                                                                     |
|  wg0 ----> Linux forwarding/NAT -----------------> upstream VPN ----+--> Internet
|   |                                                  provider       |
|   |                                                                 |
|   +----> snarkypuss-dns.service / dnsmasq                           |
|   |                                                                 |
|   +----> private management plane                                   |
|            |                                                        |
|            +--> SSH                                                 |
|            |                                                        |
|            +--> snarkyctl-web  (unprivileged)                       |
|                     |                                               |
|                     | /run/snarkyctl/control.sock                   |
|                     v                                               |
|                 snarkyctl-control (privileged)                      |
|                     |                                               |
|                     +--> provider adapter                           |
|                     +--> targets.db                                 |
|                     +--> local status collectors                    |
|                     +--> gateway-mode policy                        |
|                                                                     |
+---------------------------------------------------------------------+

Independent recovery plane: VPS console / LISH
```

There are two deliberately separate paths through this system:

- the **data plane**, which carries the Windows client's DNS and Internet traffic; and
- the **control plane**, which observes and changes gateway state.

SnarkyCtl is not in the packet-forwarding path. If the web dashboard stops, ordinary packet
forwarding is not being proxied through Python and does not stop merely because the dashboard
is unavailable.

## 2. Data plane

The data plane begins at the trusted Windows client.

The client sends traffic through the private WireGuard tunnel to the VPS. On the reference
installation:

```text
WireGuard interface:  wg0
VPS address:          10.8.0.1/24
Client address:       10.8.0.2/32
Private network:      10.8.0.0/24
```

The VPS supplies three base gateway functions:

- packet forwarding from the private client network;
- source NAT for forwarded client traffic; and
- private DNS service through a dedicated `dnsmasq` instance.

The transactional gateway setup owns identifiable base firewall/NAT chains:

```text
SNARKYPUSS_FORWARD
SNARKYPUSS_NAT
```

Those rules establish the stable client-to-VPS gateway. They do not attempt to reproduce the
upstream VPN provider's own routing and leak-protection engine.

### Provider-managed egress

The upstream VPN provider owns the parts of networking that are inherently provider-specific,
including its tunnel lifecycle, provider-created interfaces, route or policy-routing changes,
and provider leak-protection/firewall behavior.

This is intentional. Snarkypuss does not maintain a second independent routing authority that
tries to duplicate the provider's routing decisions. Doing so would create two components
competing to control the same network state.

The base gateway therefore remains stable while the provider decides whether protected
traffic is connected, blocked, or deliberately allowed to use the VPS's direct path.

## 3. Private management plane

Administrative access uses the same private WireGuard network but is logically separate from
forwarded public Internet traffic.

The private management plane includes:

- SSH to the VPS;
- SnarkyCtl HTTPS on the private management address; and
- communication between the Windows client and local gateway services such as DNS.

The reference dashboard listens only on:

```text
10.8.0.1:8443
```

It must not bind to the VPS public address or `0.0.0.0`.

The upstream provider's leak protection must preserve the private WireGuard management path
without turning SSH or SnarkyCtl into public services. For the NordVPN reference deployment,
that is why provider policy accommodates the WireGuard listener and private management subnet
rather than publicly allowlisting TCP 22 or 8443.

The VPS console/LISH is deliberately outside both WireGuard and the upstream VPN. It is the
independent recovery path if a routing, firewall, WireGuard, or provider change makes ordinary
remote management unavailable.

## 4. SnarkyCtl control plane

SnarkyCtl separates network-facing code from privileged gateway control.

```text
Browser
   |
   | HTTPS + Basic authentication
   v
snarkyctl-web
   |
   | typed local protocol
   v
/run/snarkyctl/control.sock
   |
   v
snarkyctl-control
   |
   +--> trusted provider adapter
   +--> authoritative target catalogue
   +--> status collectors
```

The web process does not execute VPN commands, alter routes, edit firewall policy, or open the
authoritative target database.

The control daemon is the privileged policy boundary. It performs authoritative target
lookup, provider invocation, catalogue mutation, and gateway-mode transitions.

The local `snarkyctl` command-line client uses the same control protocol for operational
commands. Root and the dedicated `snarkyctl` service UID are the only UIDs accepted by the
control daemon.

## 5. Privilege separation

### `snarkyctl-web.service`

The network-facing web process runs as:

```text
User=snarkyctl
Group=snarkyctl
```

The `snarkyctl` account is a non-interactive service account. It serves the authenticated
HTTPS dashboard and HTTP API and may connect to the protected Unix control socket.

It is intentionally unable to write the authoritative target database or directly perform
provider/network administration.

### `snarkyctl-control.service`

The control daemon runs as `root:root` because it must perform privileged gateway operations
and own security-sensitive persistent state.

The systemd unit constrains the service with hardening directives including
`NoNewPrivileges=true`, a restricted capability set for network administration, protected
filesystem/kernel namespaces, and explicit writable state under `/var/lib/snarkyctl`.

Root privilege is therefore concentrated behind a small local protocol instead of being
placed in the network-facing web process.

### Control socket

The systemd-managed socket is:

```text
/run/snarkyctl/control.sock
```

with the reference ownership and mode:

```text
root:snarkyctl 0660
```

Filesystem permissions are only the first check. After accepting a Unix connection, the
daemon uses Linux `SO_PEERCRED` to obtain the peer PID and UID and accepts only UID 0 or the
installed `snarkyctl` service UID.

This boundary limits **what** an authorized local process can ask root to do; it does not make
a compromise of `snarkyctl-web` harmless. Because the web process runs under an authorized
UID, a compromised web process could attempt any operation that the control protocol itself
permits. It still cannot use the protocol to execute arbitrary shell text, choose arbitrary
executables, write arbitrary root-owned files, issue unvalidated provider arguments, or bypass
the daemon's authoritative target and selector checks.

## 6. Layered validation

A state-changing browser request crosses several independent validation boundaries before a
provider command is reached.

```text
Browser/API request
      |
      v
HTTP schema + authentication + same-origin checks
      |
      v
Control protocol schema
      |
      v
Daemon operation/alias/provider checks
      |
      v
Provider selector validation
      |
      v
Fixed provider executable + fixed argument construction
```

Important consequences are:

- browsers connect by **target alias**, not arbitrary provider command text;
- extra HTTP and protocol fields are rejected;
- the protocol cannot carry an executable path or shell fragment;
- the daemon performs the authoritative alias lookup again;
- structured selectors are validated by the active compiled adapter; and
- provider commands use fixed executable paths, argument arrays, bounded output/timeouts,
  and `shell=False`.

Validation is intentionally repeated at trust boundaries rather than assuming that a request
validated by the browser or web process is safe to execute as root.

## 7. Control protocol

The web/CLI-to-daemon boundary uses a private, versioned Unix-socket protocol.

The current protocol version is:

```text
3
```

Messages are UTF-8 JSON inside a size-prefixed stream frame. Requests and responses are
strictly schema validated, unknown fields are forbidden, and a complete message is bounded to
512 KiB.

The protocol exposes a fixed operation enumeration rather than arbitrary procedure names:

```text
STATUS
TARGETS
CONNECT
DISCONNECT
PROTECTED
LOCK
DIRECT
TARGET_SCHEMA
TARGET_OPTIONS
TARGET_CATALOG_GET
TARGET_CATALOG_REPLACE
```

The protocol is an internal privilege boundary, not a general-purpose remote procedure call
mechanism.

### Ordinary versus administrative target data

`TARGETS` returns sanitized aliases, labels, and provider capabilities suitable for ordinary
clients.

The administrative operations expose structured selector data only when it is required to
manage the catalogue:

```text
TARGET_SCHEMA
TARGET_OPTIONS
TARGET_CATALOG_GET
TARGET_CATALOG_REPLACE
```

`TARGET_OPTIONS` is read-only discovery. The daemon validates its provider, selector kind,
field, option source, and dependency context against the active provider schema before the
adapter can perform provider-specific discovery.

This separation prevents provider-specific selector documents from leaking into ordinary
status or connection flows.

## 8. Provider abstraction

Provider-specific behavior is isolated behind the `VpnProvider` abstraction.

Conceptually:

```text
                    +--> Provider A adapter --> provider-native operations
SnarkyCtl daemon ---|
                    +--> future adapter ------> its native operations
```

A provider adapter owns translation between SnarkyCtl's provider-neutral concepts and the
provider's native command/API surface.

The core provider contract includes concepts such as:

- status;
- settings relevant to safety decisions;
- connect/disconnect;
- target-schema and selector validation when target selection is supported;
- provider-backed target-option discovery when the provider supports it; and
- leak-protection configuration when the provider supports it.

### Provider-neutral target discovery

Target discovery extends the provider abstraction without moving provider semantics into the
browser or HTTP layer.

A schema choice field declares whether its options are static or provider-backed. A
provider-backed field may also declare dependencies on other fields in the same selector kind.
The generic flow is:

```text
dashboard
   |
   | kind + field + declared dependency context
   v
authenticated target-options HTTP endpoint
   |
   v
TARGET_OPTIONS control request
   |
   v
privileged daemon schema/context validation
   |
   v
compiled provider adapter
   |
   | bounded provider-native discovery
   v
TargetOption(value, label) records
   |
   v
generic dashboard choice control
```

The unprivileged web process never runs provider discovery commands. The privileged daemon
admits only fields that the reviewed schema marks as provider-backed and requires the exact
declared dependency context. The adapter owns provider-native discovery, output parsing,
normalization, and limits.

Discovery values are editing assistance, not a replacement for authoritative validation. A
selector is validated by the adapter before storage and again before use. Advanced text
selectors may intentionally receive only structural safety validation; for example, a
Specific server identifier can be stored without proving that the provider currently offers
that server, and a semantic error may therefore occur at connection time.

### Fixed provider registry

Provider selection is not dynamic Python module loading.

The configured provider name is looked up in a fixed registry of reviewed factories compiled
into the installed release. An unknown configured provider is rejected.

The current release registers NordVPN. The important architectural property is that the HTTP
API, control protocol, target catalogue, and dashboard do not need to become NordVPN-specific
when another reviewed adapter is added later.

This is conventional object-oriented polymorphism in Python: the daemon depends on the
`VpnProvider` interface while concrete adapters implement provider-specific behavior.

## 9. Configuration and state ownership

Snarkypuss deliberately separates different kinds of state according to who is authoritative
for them.

| State | Authoritative owner |
|---|---|
| Base gateway/WireGuard/DNS configuration | Root-controlled operating-system configuration |
| SnarkyCtl service/network policy | `/etc/snarkyctl/snarkyctl.yaml` |
| Approved VPN destinations | Provider-scoped target repository / SQLite catalogue |
| Current committed catalogue snapshot | Privileged control daemon memory |
| Provider connection/settings state | Upstream provider, observed through its adapter |
| Dashboard presentation state | Browser only; never authoritative |

### Main YAML configuration

`/etc/snarkyctl/snarkyctl.yaml` defines stable installation policy: management/public
interfaces, private listener, control socket, provider registry name, status endpoint, and
target-storage backend.

It is configuration, not frequently edited operational state.

### SQLite target repository

The normal target repository is:

```text
/var/lib/snarkyctl/targets.db
```

It is root-controlled because only the privileged daemon opens it in production.

The repository is provider-scoped. Alias and ordering uniqueness apply within a provider's
catalogue, and each provider catalogue has an independent revision.

The domain/control layers depend on the `TargetRepository` contract rather than issuing SQL
directly. SQLite is therefore a storage implementation, not part of the provider or HTTP
interface.

### Atomic catalogue replacement

The dashboard edits a complete ordered catalogue and submits it with an expected revision.
The daemon validates every selector through the active adapter before storage.

Replacement then occurs in one repository transaction:

```text
read current revision
       |
validate complete proposed catalogue
       |
compare expected revision
       |
replace rows + increment revision
       |
commit
       |
replace daemon in-memory snapshot
```

The daemon updates its live in-memory catalogue only **after** the database transaction
commits successfully.

A stale revision produces `CATALOG_CONFLICT`; it does not silently overwrite another
administrator's newer edit.

### Built-in and compatibility targets

A provider may declare a parameterless `recommended` selector as a built-in public target.
When present, the daemon synthesizes the reserved alias `recommended` at runtime instead of
persisting a row in SQLite. Ordinary target listings include it; the editable catalogue does
not. This permits an otherwise empty persisted catalogue while still retaining a usable
provider-selected default target.

Legacy selectors remain a compatibility mechanism for previously migrated values. Existing
legacy rows remain visible to administration so they can be connected, converted, or deleted,
but the dashboard does not offer Legacy as a type for newly created targets.

For provider-backed discovered choices, the dashboard treats a saved value that disappears
from current discovery as stale. It never silently substitutes a different value and normally
cleans up the unavailable persisted destination automatically; failed automatic cleanup is
surfaced for administrator action.

## 10. Gateway modes are observed state

SnarkyCtl exposes four gateway modes:

```text
VPN
LOCKED
DIRECT
UNKNOWN
```

They describe the observed relationship between provider connection state and leak-protection
state. They are not simply a record of which button the user last pressed.

The current derivation is:

| Observed provider state | Observed leak protection | Gateway mode |
|---|---|---|
| Connected | reported separately | `VPN` |
| Disconnected | enabled | `LOCKED` |
| Disconnected | disabled | `DIRECT` |
| Anything indeterminate | unknown/incompatible | `UNKNOWN` |

A `VPN` mode therefore means the upstream provider reports a connected state; the separate
`leak_protection_active` field still records whether leak protection could be verified.

`UNKNOWN` is intentionally not treated as protected.

### Protected transition

Protected mode is an ordered policy operation:

```text
enable provider leak protection
        |
connect approved target alias
        |
observe resulting state
```

The daemon resolves the alias to the committed structured selector and asks the active
provider adapter to connect it.

### Locked transition

Locked mode is:

```text
enable provider leak protection
        |
disconnect provider
        |
observe disconnected + protected state
```

The design goal is to block forwarded public traffic while preserving the private WireGuard
management path.

### Direct transition

Direct VPS mode is exceptional:

```text
require exact confirmation
        |
disable provider leak protection
        |
disconnect provider
        |
observe disconnected + unprotected state
```

The confirmation token is deliberately exact:

```text
EXPOSE VPS IP
```

If a Direct transition fails after leak protection has been disabled, the daemon attempts to
restore provider leak protection before reporting the failure.

### No automatic Direct fallback

A provider failure, timeout, reboot, or unsuccessful connection must not be interpreted as a
request for Direct VPS mode. Direct exposure is an explicit policy decision, never an
automatic fallback.

## 11. Provider-managed egress policy

An earlier architectural direction contemplated a separate provider-neutral firewall mode
engine that would independently enforce Protected, Locked, and Direct forwarding paths.

The current architecture instead treats provider routing and provider leak protection as one
authority.

This choice avoids two independent controllers trying to manipulate:

- default routes;
- provider policy-routing tables;
- provider-created interfaces; and
- the provider kill switch/firewall.

Snarkypuss owns the stable base gateway; the provider owns its egress machinery; the adapter
coordinates supported provider operations; and SnarkyCtl observes the resulting state.

This also explains why the real fail-closed acceptance test remains important. A local
configuration check can verify that leak protection is reported enabled, but only an actual
provider-disconnect test with the Windows client can prove that forwarded traffic does not
escape through the VPS public path.

## 12. Status architecture

Status collection is deliberately observational.

The control daemon builds a gateway snapshot from several independent sources:

- provider connection status;
- provider safety/settings state;
- `snarkypuss-dns.service` state;
- basic local host health; and
- observed public IPv4 when the gateway is in a mode where public egress is expected.

A failure in one collector does not necessarily destroy the whole snapshot. Component
failures are returned as bounded `partial_failures`, allowing the dashboard to show available
information without pretending that missing information is safe.

### Public-IP observation

The configured public-IP service is queried only when the observed gateway mode is `VPN` or
`DIRECT`.

It is not queried in `LOCKED`, where public forwarding should be blocked, or when the mode is
indeterminate.

The collector uses verified HTTPS, bounded response size, no redirect following, and accepts
only a valid IPv4 response.

## 13. Mutation serialization and concurrency

The control daemon may serve multiple local socket connections concurrently so read-only
status and catalogue queries remain responsive.

Mutating operations share one non-blocking operation lock. The protected set includes:

- connect;
- disconnect;
- Protected mode;
- Locked mode;
- Direct mode; and
- target-catalogue replacement.

Only one such operation is admitted at a time. A competing mutation immediately receives:

```text
OPERATION_IN_PROGRESS
```

rather than waiting behind a long provider operation.

The lock is released on success or failure, including provider exceptions and timeouts.

## 14. HTTP security boundary

The HTTPS layer adds authentication and browser-origin protections before any request can
reach the privileged protocol.

Operational endpoints use HTTP Basic authentication over TLS. The password file contains
bcrypt hashes rather than plaintext credentials.

State-changing requests additionally require:

```text
Content-Type: application/json
X-SnarkyCtl-Request: 1
```

Browser requests are restricted to the same origin using Fetch Metadata and `Origin` checks,
and CORS is not enabled.

The API also sends restrictive security headers, disables FastAPI documentation/schema
routes in production, and serves dashboard scripts/styles from the same origin.

These HTTP protections are important, but they do not replace daemon-side validation. The
privileged daemon remains authoritative even if the web process has already validated a
request.

## 15. DNS architecture

Snarkypuss runs a dedicated `dnsmasq` instance as `snarkypuss-dns.service` for the WireGuard
client. The resolver reads only the generated Snarkypuss configuration:

```text
/etc/snarkypuss/dnsmasq.conf
```

The service invokes `/usr/sbin/dnsmasq` with that file explicitly. It does not use Ubuntu's
stock `dnsmasq.service`, `/etc/dnsmasq.conf`, or `/etc/dnsmasq.d/` for the active private
resolver.

The dedicated unit requires and starts after the configured WireGuard service. Its dnsmasq
configuration uses `bind-dynamic`, binds to the private gateway address, and uses only the
configured upstream resolvers (`no-resolv`). This keeps distro-global dnsmasq defaults from
silently changing Snarkypuss DNS behavior.

The Windows client sends DNS requests through WireGuard to the VPS. The private dnsmasq
instance forwards those queries according to its configured upstreams, and the resulting
traffic follows the VPS's current routing/provider policy.

DNS is deliberately kept out of the SnarkyCtl web process. SnarkyCtl observes the systemd
service state but does not act as a DNS proxy.

## 16. systemd lifecycle

systemd provides process lifecycle, socket activation, logging, ordering, and operating-system
hardening.

The principal SnarkyCtl units are:

```text
snarkyctl-control.socket
snarkyctl-control.service
snarkyctl-web.service
```

The control socket is systemd-owned. The privileged daemon is socket activated and requires
exactly one inherited Unix stream listener rather than creating its own competing socket.

The web service starts separately and connects through that socket.

The broader gateway also relies on systemd ordering for WireGuard and the dedicated
`snarkypuss-dns.service`.

## 17. Failure model

Snarkypuss is designed around explicit and observable failure rather than silent fallback.

### Provider connection failure

A failed provider connection is an error. It is not permission to expose the VPS public path.
The existing leak-protection state remains significant and should normally leave the gateway
blocked rather than Direct.

### Provider status/settings unavailable

If SnarkyCtl cannot establish enough state to classify the gateway safely, the result becomes
`UNKNOWN` or a partial failure. Missing information is not converted into a reassuring
protected state.

### Web process failure

The dashboard/API becomes unavailable, but the web process is not the packet-forwarding data
plane and does not own provider routes or the target database.

### Control daemon failure

New management operations fail, but the provider and kernel retain their current network
state. Clients must not assume that daemon unavailability implies either protection or
exposure; the observable state must be checked after recovery.

### Database/catalogue failure

Catalogue mutation fails closed: a failed transaction does not replace the daemon's last
committed in-memory catalogue. An unknown or stale catalogue is not silently accepted.

### Management-path failure

LISH remains the recovery plane independent of WireGuard and provider networking.

## 18. Security principles

The architecture follows several recurring principles:

1. **Least privilege at the network boundary.** The HTTPS service is unprivileged.
2. **Small privileged interface.** Root operations are reachable only through a bounded local
   command protocol.
3. **Authoritative lookup at the privileged boundary.** Clients send aliases; root resolves
   selectors.
4. **No arbitrary shell surface.** Fixed executables and argument arrays replace shell text.
5. **Provider ownership of provider networking.** Snarkypuss does not create a second routing
   authority.
6. **Fail closed rather than fall back to Direct.** Exposure requires an explicit operation.
7. **Observed state over assumed success.** Provider state is queried after mutations.
8. **Atomic authoritative storage.** Catalogue edits commit transactionally with optimistic
   concurrency.
9. **Private management by default.** HTTPS and SSH remain on WireGuard, not the public VPS
   interface.
10. **Independent recovery.** VPS console access remains available when network policy goes
    wrong.
11. **Provider-neutral discovery.** Generic clients request only schema-declared options;
    provider-native discovery stays inside the trusted adapter.

## 19. Design patterns used

Several conventional software-design patterns are visible in the implementation:

- **Adapter / Strategy:** `VpnProvider` implementations translate provider-neutral operations
  into provider-native behavior.
- **Registry / Factory:** only reviewed provider implementations compiled into the release can
  be selected.
- **Repository:** target-domain/control logic is independent of SQLite details.
- **Command:** control-protocol operations are bounded commands crossing a privilege boundary.
- **Data-transfer / anti-corruption layer:** public and protocol models prevent provider CLI
  syntax from leaking through the system.
- **Optimistic concurrency:** catalogue revisions prevent lost updates.
- **Unit of Work:** one transaction commits a complete catalogue replacement.
- **Capability model:** the UI and API can adapt to what the active provider says it supports
  without hard-coding a provider name into ordinary client behavior.

## 20. Implementation technologies

The architecture is implemented with deliberately modest components:

- **Python 3** for application and control logic;
- **Pydantic** for strict typed models and validation;
- **FastAPI** for the private HTTP API;
- **Uvicorn** as the HTTPS application server;
- **Jinja2** plus plain HTML/CSS/JavaScript for the dashboard;
- **SQLite** for the mutable target catalogue;
- **systemd** for service lifecycle, socket activation, ordering, and hardening;
- **WireGuard** for the private client-to-VPS tunnel; and
- **dnsmasq** for private gateway DNS.

These technologies support the architecture; they are not the architecture themselves.

The system intentionally avoids adding a reverse proxy, container orchestration platform,
frontend build pipeline, job queue, or external application database where those components
would not strengthen the trust model or operating requirements of this small private gateway.

## 21. Architectural invariants

A deployment remains recognizably Snarkypuss only while these properties hold:

- the management interface is private;
- the Windows client reaches the VPS through WireGuard;
- base forwarding/NAT is distinct from provider-owned egress policy;
- Direct VPS exposure is explicit, never automatic;
- the network-facing SnarkyCtl process is not privileged;
- the privileged daemon is reached only through the protected local protocol;
- the daemon, not the browser, owns authoritative target resolution;
- only compiled provider adapters may perform provider operations;
- authoritative mutable target state is not writable by the web-service account;
- unknown or incomplete safety state is not reported as protected; and
- an independent VPS-console recovery path remains available during risky network changes.

Those invariants are more important than any particular provider, hosting company, Linux
interface name, or frontend technology.
