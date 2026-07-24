# Snarkypuss Architecture Decisions

This document records requirements-baseline decisions for the Snarkypuss private VPN gateway and its SnarkyCtl management utility. They are architectural constraints rather than incidental implementation details. A later ADR may explicitly supersede an earlier decision while preserving the history and rationale.

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

**Status:** Partially superseded by ADR-013. The original decision is retained to show the former ownership model. Snarkypuss no longer implements provider mode transitions by selecting provider-specific forwarding paths in its base firewall.

**Original decision:** Locked behaviour is enforced by firewall and forwarding policy, not by periodic health monitoring alone.

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

**Status:** Partially superseded by ADR-013. The trusted adapter registry and normalized provider boundary remain accepted. The statements assigning VPN, Direct VPS, and Locked enforcement to a separate provider-neutral firewall mode engine are superseded.

**Original decision:** Core policy, protocol, API, status models, and firewall logic refer to an optional upstream VPN rather than NordVPN.

A fixed compiled registry selects a trusted `VpnProvider` adapter. Configuration may choose a registered provider name but may not load an arbitrary Python module. The first built-in implementation is `NordVpnProvider`; generic WireGuard and OpenVPN adapters may be added later.

Provider adapters own provider-specific command execution and parsing. They return common status models and a verified upstream interface. They do not construct firewall rules. The provider-neutral firewall layer implements VPN, Direct VPS, and Locked modes.

The distributed systemd units have no hard dependency on `nordvpnd.service`. Provider-specific service ordering may be added through an administrator-controlled systemd drop-in.


## ADR-013: Provider-managed egress policy with transactional base activation

**Status:** Accepted. This decision supersedes the mode-enforcement portions of ADR-004 and ADR-012.

### Context

Snarkypuss has two distinct networking responsibilities:

1. It provides the private client-to-VPS tunnel, DNS listener, IPv4 forwarding, and source NAT needed for the VPS to act as a gateway.
2. An independently installed upstream VPN provider decides how forwarded traffic leaves the VPS.

The original design assigned Protected VPN, Locked, and Direct VPS modes to a
provider-neutral firewall layer. That layer would permit forwarding only through a verified
provider interface in Protected mode, create a separate public-interface path for Direct VPS
mode, and remove both paths in Locked mode.

Implementation work exposed several problems with that ownership model:

- A mature provider application already manages its tunnel, routes, policy-routing rules,
  firewall integration, connection lifecycle, and kill switch.
- Reimplementing those decisions in Snarkypuss would duplicate provider behavior and create
  two authorities over the same network state.
- An interface-bound base firewall would block intentional Direct VPS mode unless Snarkypuss
  also understood how each provider transitions out of its tunnel.
- Provider implementations do not necessarily express protection through the same interface,
  route-table, or firewall pattern. Treating interface disappearance as the universal Locked
  signal is not provider-neutral.
- The private WireGuard transport must remain reachable while provider routing changes. The
  required firewall mark and any matching provider exemption are a coordinated provider
  configuration concern, not a generic route that Snarkypuss should invent.
- Editing routes directly would violate the established rule that the underlying VPN
  application should perform routing when it is capable of doing so.

At the same time, gateway activation still needs to enable kernel forwarding, install source
NAT, start the private tunnel and DNS service, persist the accepted firewall state, and avoid
locking an administrator out of a remote VPS.

### Decision

Responsibility is divided as follows.

#### Snarkypuss base gateway owns

- The private WireGuard interface and client peer configuration.
- The tunnel address and DNS listener.
- Runtime IPv4 forwarding.
- Generic forwarding of the configured private client network.
- Generic source masquerading for that client network.
- Dedicated, identifiable iptables chains named `SNARKYPUSS_FORWARD` and
  `SNARKYPUSS_NAT`.
- Transactional activation, confirmation, persistence, and rollback.
- Read-only structural verification and public-egress observation.

#### The upstream provider and its trusted adapter own

- Provider connection and disconnection.
- Provider target selection.
- Default routes and policy-routing tables.
- Provider-created interfaces.
- The provider kill switch or equivalent fail-closed behavior.
- The transition among Protected VPN, Locked, and explicitly requested Direct VPS states.
- Provider-specific firewall or routing exclusions needed to keep private management traffic
  reachable.
- Interpretation of provider-specific status and capabilities.

The base activation script does not add, delete, replace, or infer routes. It does not invoke
a provider command and does not edit provider firewall rules. Its NAT rule does not bind to a
specific outbound interface; traffic follows the route selected by the provider.

The setup field `protected_egress_interface` is a precondition and diagnostic assertion.
The named interface must exist when activation begins, showing that the expected protected
provider path is present. It is not embedded as a permanent outbound match in the base NAT
or forwarding rules.

The setup field `tunnel_fwmark` is written to the private WireGuard configuration. Its value
must be coordinated with the selected provider's routing policy so WireGuard management
transport bypasses the upstream tunnel correctly. Snarkypuss validates and renders the mark
but does not manufacture the corresponding provider policy.

### Gateway-mode consequences

This ownership model preserves all three user-visible modes without embedding
provider-specific routing in the base gateway:

| Mode | Authority and behavior |
|---|---|
| **Protected VPN** | The provider is connected and selects its protected route. Its kill switch is enabled. Generic Snarkypuss forwarding and NAT follow that route. |
| **Locked** | The provider's fail-closed policy blocks Internet egress while the private management path remains available. Snarkypuss does not silently create a public fallback route. |
| **Direct VPS** | A trusted provider adapter performs the explicit, confirmed transition required to allow public VPS egress. Generic Snarkypuss forwarding and NAT then follow the provider-selected public route. |

Direct VPS mode remains exceptional and must continue to display a prominent warning that
the real public VPS IP is exposed. The base activation workflow never selects Direct VPS mode
and never treats provider failure as permission to use it.

A provider that cannot supply reliable fail-closed behavior or a safe explicit Direct
transition must report that limitation through its adapter capabilities. The UI must not
offer a mode that the installed adapter cannot enforce.

### Transactional activation protocol

Configuration generation and activation are separate operations. Generation may write
inactive WireGuard, dnsmasq, and sysctl files, but it does not load them or change live
network state.

Before activation, the administrator must explicitly assert both:

- Independent VPS console access has been tested.
- Provider kill-switch or equivalent leak protection has been configured and tested.

The activation sequence is:

1. Parse and validate the root-owned setup document.
2. Require the configured protected provider interface to exist.
3. Validate the generated WireGuard configuration with `wg-quick strip`.
4. Validate dnsmasq configuration with `dnsmasq --test`.
5. Capture the complete current iptables state.
6. Capture the runtime `net.ipv4.ip_forward` value.
7. Capture active and enabled states for WireGuard and dnsmasq.
8. Capture the existing persistent IPv4 rules file, if present.
9. Write a root-only activation record under
   `/var/lib/snarkypuss/activations/`.
10. Schedule a transient systemd rollback timer.
11. Replace only the dedicated Snarkypuss chains and their parent-chain jumps.
12. Enable runtime IPv4 forwarding.
13. Enable and start the private WireGuard and DNS services.
14. Print a random activation token and require separate confirmation.

The rollback timer is scheduled **before** the first network mutation. Firewall rules are
not saved persistently during the provisional interval.

Confirmation requires the exact token. It cancels the timer, runs
`netfilter-persistent save`, and changes the activation record from `pending` to
`confirmed`.

If confirmation does not arrive, automatic rollback restores:

- The complete pre-activation iptables snapshot.
- The previous runtime forwarding value.
- The former active and enabled state of WireGuard.
- The former active and enabled state of dnsmasq.

A confirmed activation may be rolled back later with an explicit `--force`. Because that
operation restores a complete firewall snapshot and the former persistent rules file, it can
discard unrelated firewall changes made after activation. The operator must inspect current
state and ensure console access before forcing a historical rollback.

Activation records are mode `0600`, stored in a root-only directory, and contain no
WireGuard private key.

### Firewall structure

The activation workflow must not flush a built-in table or chain. In particular, it must
never run `iptables -t nat -F POSTROUTING`.

Instead, it owns two dedicated chains:

- `SNARKYPUSS_FORWARD` accepts established return traffic and client traffic arriving from
  the configured private tunnel, then returns to the surrounding firewall policy.
- `SNARKYPUSS_NAT` masquerades only the configured private client network, then returns.

One jump is inserted into `FORWARD` and one into the NAT `POSTROUTING` chain. Repeated
activation removes and recreates only these owned chains. Existing provider and administrator
rules remain intact during application.

The complete firewall snapshot is used only for rollback, where restoring exact pre-change
state is more important than preserving changes made during the short provisional window.

### Rejected alternatives

**Provider-interface-only forwarding in the base firewall:** Rejected because it duplicates
provider mode logic, assumes a universal interface model, and blocks provider-controlled
Direct VPS operation.

**Separate public and protected routes managed by Snarkypuss:** Rejected because route
ownership belongs to the underlying VPN provider where that provider already implements it.

**Automatic default-route discovery:** Rejected because choosing a public interface
implicitly could expose the VPS IP and make behavior depend on transient route state.

**WireGuard `PostUp` and `PostDown` firewall commands:** Rejected because they scatter
firewall ownership into service configuration, provide no complete transaction, and make
rollback and inspection harder.

**Flushing built-in chains before installing rules:** Rejected because it can destroy
provider, cloud, container, or administrator firewall state.

**Immediate persistent activation:** Rejected because a bad firewall, DNS, or tunnel change
could sever remote access and survive reboot.

**No automatic timer:** Rejected because an SSH session is not an adequate confirmation
channel when the operation itself may interrupt that session.

### Security consequences

This decision avoids competing route controllers and makes activation recoverable, but it
also makes provider leak protection a hard dependency. Generic forwarding and NAT cannot by
themselves distinguish an intentional Direct VPS state from an accidental provider failure.

Therefore:

- Activation requires the explicit
  `--provider-leak-protection-confirmed` acknowledgement.
- Documentation must instruct operators to test the provider kill switch before activation.
- A missing acknowledgement is a hard failure, not a warning.
- Read-only verification must describe observed egress as evidence, not proof of the complete
  forwarded client path.
- A public-IP mismatch is consistent with protected egress but does not prove it.
- A failed public-IP lookup may indicate Locked mode or an unrelated failure.
- Direct VPS exposure must remain explicit, confirmed, and visibly dangerous in SnarkyCtl.
- Future provider adapters must document their routing, kill-switch, management-bypass, and
  Direct-mode guarantees.

### Operational and development consequences

- `scripts/snarkypuss-migrate.py` provides an audit-first, file-transactional path from
  the original manual gateway to managed configuration. It preserves the existing server
  private key and client peer, records checksums and original file modes in a root-only
  backup, and never changes live networking.
- Migration preparation omits legacy WireGuard lifecycle hooks and hands generation to the
  canonical configuration tool. Runtime cutover remains a separate rollback-protected
  activation; file restoration and runtime rollback are deliberately distinct operations.
- `scripts/snarkypuss-configure.py` renders `tunnel_fwmark` but no firewall hooks.
- `scripts/snarkypuss-activate.py` owns provisional activation and confirmation.
- `scripts/snarkypuss-rollback.py` owns automatic and forced restoration.
- `scripts/snarkypuss-verify.sh` inspects the dedicated chains but remains read-only.
- The technical reference must not instruct users to flush built-in chains.
- The privileged SnarkyCtl daemon and provider adapters must remain consistent with this
  ownership boundary; core code must not become a second provider route manager.
- Tests must verify that rollback is scheduled before firewall mutation, that no route command
  is introduced, that explicit leak-protection acknowledgement is required, and that the
  dedicated firewall chains are used.


## ADR-014: Provider-neutral target catalogues in SQLite

**Status:** Accepted.

### Context

SnarkyCtl currently reads one root-owned YAML target allowlist. Each entry contains a
provider-neutral alias and label plus a single `provider_target` string. This is safe for a
small manually maintained NordVPN deployment, but it has important limitations:

- Adding, editing, removing, or reordering destinations requires a root shell, validation,
  and a daemon restart.
- A single string reflects the command-line shape of NordVPN and cannot naturally represent
  an OpenVPN profile, a structured Mullvad location, a recommended-server policy, or another
  provider's selector.
- The catalogue is implicitly tied to the active provider. Changing providers would either
  overwrite the existing destinations or leave ambiguous values behind.
- A future dashboard editor needs transactional updates, conflict detection, schema
  migration, and recovery without granting the network-facing web process arbitrary
  filesystem write access.
- Partial per-entry mutations could leave a catalogue in an invalid intermediate state.

The catalogue remains small, local, and single-writer. A database server and a general
multi-user SQL deployment would add operational complexity without benefit. At the same
time, an embedded transactional store is preferable to reimplementing database semantics
around a collection of mutable files.

### Decision

SnarkyCtl will store managed destination catalogues in an embedded SQLite database. SQLite
is a storage implementation behind a repository interface; it is not exposed as part of the
HTTP API, daemon protocol, provider interface, or dashboard model.

The canonical database path will be:

```text
/var/lib/snarkyctl/targets.db
```

The database and any SQLite journal files are owned by `root:root` and are not writable or
directly readable by the `snarkyctl` service account. The containing directory is writable
only by root. The privileged control daemon is the sole database writer and reader. The web
service obtains sanitized target information and submits narrowly typed catalogue operations
only through `/run/snarkyctl/control.sock`.

This deliberately preserves the existing privilege boundary. Ownership by the unprivileged
web account was rejected because compromise of that process would then permit direct
replacement of the authoritative provider allowlist.

Python's standard `sqlite3` module will be used. SnarkyCtl will not introduce a separate
database daemon, network listener, database account, ORM, Berkeley DB runtime, or native
third-party database binding for this feature.

### Provider-scoped storage model

The database stores independent catalogues under provider registry names such as
`nordvpn`, `mullvad`, and `openvpn`. Only providers compiled into the trusted registry
may own a catalogue.

A conceptual target record contains:

```text
provider
alias
label
position
selector_kind
selector_document
```

The exact normalized relational schema may evolve during implementation, but it must enforce
at least:

- A database schema version.
- A monotonically increasing catalogue revision.
- A unique alias within each provider.
- A unique ordering position within each provider.
- A bounded label and selector document.
- Referential integrity between a catalogue and its target records.
- Deterministic ordering.
- No executable path, Python module name, shell text, or arbitrary command representation in
  core target fields.

Provider catalogues coexist. Changing the active provider does not delete or reinterpret
another provider's destinations. A connection operation resolves an alias only within the
currently configured provider.

### Structured provider selectors

The core target model will no longer treat a destination as one universally meaningful
string. Each target has a structured selector document owned by its compiled adapter.

Examples are illustrative:

NordVPN city:

```json
{
  "kind": "city",
  "country": "US",
  "city": "Dallas"
}
```

NordVPN recommended server:

```json
{
  "kind": "recommended"
}
```

Mullvad location:

```json
{
  "kind": "location",
  "country": "se",
  "city": "got"
}
```

OpenVPN profile:

```json
{
  "kind": "profile",
  "profile_id": "private-us-east"
}
```

The selector document is stored as bounded canonical JSON or an equivalent normalized
relational representation. SQLite does not decide whether a selector is meaningful. Before
storage and again before use, the corresponding compiled adapter validates the selector,
rejects unknown fields, and converts the validated value into its own safe operation.

Adapters must construct fixed argument arrays or use fixed configuration objects. A selector
must never be concatenated into shell text.

### Provider adapter contract

The existing `VpnProvider` Strategy interface will be extended with target capabilities
similar to:

```python
def target_schema(self) -> ProviderTargetSchema: ...
def validate_selector(self, selector: JsonObject) -> ValidatedSelector: ...
def connect(self, target: StoredTarget) -> VpnStatus: ...
```

The names may change during implementation, but the responsibilities may not:

- The core owns aliases, labels, ordering, revisions, persistence, and protocol framing.
- The adapter owns selector kinds, selector validation, provider discovery semantics, and
  translation into provider operations.
- The trusted provider registry remains the only provider factory. Database content cannot
  dynamically load an adapter.

An adapter may expose fixed target-schema metadata so the generic dashboard can render an
appropriate editor. That metadata is data, not provider-supplied HTML or executable code. It
may describe only a small reviewed set of field types, lengths, choices, and required flags.

A provider that does not support target selection reports that capability. The dashboard
must not invent or display a target editor for it.

### Repository pattern

Daemon business logic will depend on a storage abstraction such as:

```python
class TargetRepository:
    def get_catalogue(self, provider: str) -> TargetCatalogue: ...
    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue: ...
```

The first implementation is `SqliteTargetRepository`. Tests may use an in-memory repository
or a temporary SQLite database through the same contract. No provider adapter, protocol
handler, API route, or dashboard component may issue SQL directly.

This Repository pattern keeps the choice of SQLite out of the domain and protocol layers.
Changing the storage implementation later does not change provider adapters or public API
objects.

### Atomic replacement and optimistic concurrency

Catalogue editing uses complete-catalogue replacement rather than independent create, update,
delete, and reorder writes.

A read returns the provider and current revision. A replacement includes
`expected_revision` and the complete proposed ordered target list. The daemon:

1. Verifies the requesting process through the existing Unix-socket peer checks.
2. Confirms that the provider is compiled and eligible for catalogue administration.
3. Enforces catalogue size, alias, label, ordering, and request-size limits.
4. Asks that provider's adapter to validate every selector.
5. Begins one SQLite transaction.
6. Compares `expected_revision` with the stored revision.
7. Replaces the provider's targets and increments its revision.
8. Commits only if the complete catalogue is valid.
9. Replaces the daemon's in-memory snapshot only after commit.
10. Returns the new revision and sanitized catalogue.

A stale revision returns `CATALOG_CONFLICT` without changing the database. This prevents
two dashboard tabs or clients from silently overwriting each other.

SQLite will use foreign-key enforcement, a bounded busy timeout, durable transaction
settings, and explicit transaction boundaries. The implementation must account for every
database sidecar file in ownership, backup, package upgrade, and recovery procedures.

### Daemon protocol

The versioned control protocol will add three provider-neutral operations:

```text
TARGET_SCHEMA
TARGET_CATALOG_GET
TARGET_CATALOG_REPLACE
```

Their responsibilities are:

- `TARGET_SCHEMA`: Return the selected compiled adapter's bounded editor metadata and target
  capabilities.
- `TARGET_CATALOG_GET`: Return an editable provider-scoped catalogue and revision to an
  authenticated administrative caller.
- `TARGET_CATALOG_REPLACE`: Validate and atomically replace one provider catalogue using an
  expected revision.

Ordinary target discovery remains sanitized. The existing browser catalogue endpoint and
routine status responses continue to expose only aliases and labels. Provider selector
documents are available only through a distinct authenticated administrative operation and
must never appear accidentally in the ordinary dashboard response.

Connection remains an alias-based command:

```text
CONNECT <alias>
```

The daemon resolves the alias against the active provider's committed in-memory catalogue.
The browser never sends a selector as part of a connection request.

Protocol messages remain bounded, versioned, strictly schema-validated, and free of unknown
fields. Stable failures will include at least:

```text
INVALID_CATALOG
UNKNOWN_PROVIDER
UNSUPPORTED_TARGET_SELECTION
CATALOG_CONFLICT
CATALOG_STORAGE_FAILED
CATALOG_MIGRATION_REQUIRED
```

The precise error enumeration will be finalized with the protocol models and tests.

### HTTP API and dashboard

Catalogue administration uses separate authenticated endpoints from ordinary catalogue
display. State-changing requests retain HTTP Basic authentication, exact-origin checks,
JSON-only content, and the dedicated request marker header.

The dashboard editor is generated from core fields plus the active adapter's bounded schema
metadata. It must support adding, editing, deleting, and reordering destinations, but it
submits the complete catalogue and expected revision in one request.

The UI must:

- Identify the provider whose catalogue is being edited.
- Distinguish aliases from labels.
- Explain that aliases are stable API identifiers.
- Warn before deleting a destination.
- Refuse to save an empty catalogue.
- Show a conflict rather than overwriting a newer revision.
- Never display a selector for one provider as though it belonged to another.
- Keep provider auto-connect policy separate from the selectable destination catalogue.

### Migration from targets.yaml

The existing `/etc/snarkyctl/targets.yaml` file remains authoritative until an explicit
administrator-run migration succeeds. Package installation or upgrade must not silently
replace it.

A migration tool will:

1. Read and validate the existing main configuration and YAML target catalogue.
2. Select the compiled adapter named by `upstream_vpn.provider`.
3. Create a root-only backup of the YAML file and any existing destination database.
4. Initialize or migrate the SQLite schema transactionally.
5. Preserve aliases, labels, and entry order.
6. Convert each existing `provider_target` through an adapter-owned legacy import method.
7. Abort the complete migration if any value cannot be represented safely.
8. Verify the committed catalogue through the repository.
9. Leave the YAML backup available for explicit rollback.
10. Require a deliberate configuration change before SQLite becomes authoritative.

Because a legacy string may not reveal whether it denotes a country, city, group, or server,
the importer must not guess. An adapter may preserve it temporarily using a narrowly
validated legacy selector kind, or require the administrator to classify it. New dashboard
entries must use the structured selector forms.

Migration is idempotent and does not connect, disconnect, or reconfigure the VPN provider.
It does not change routes, firewall rules, WireGuard, DNS, or provider auto-connect state.

### Backup, integrity, and recovery

The database contains configuration, not passwords or private keys, but it remains
security-sensitive because it controls approved provider destinations.

Operational requirements include:

- Root-only database writes.
- No symbolic-link following for database creation, migration, backup, or restore.
- A consistent SQLite backup operation rather than copying an active database blindly.
- A pre-migration and pre-upgrade backup.
- Schema migrations inside an explicit transaction.
- Integrity checking after migration and restore.
- Documented recovery to the previous database or YAML catalogue.
- No automatic fallback to an unvalidated or corrupt catalogue.
- Fail-closed behavior when the active provider has no valid committed targets.

### Design patterns

This decision applies the following patterns:

- **Strategy:** `VpnProvider` implementations own provider behavior.
- **Registry and Factory:** only compiled, reviewed providers can be selected.
- **Repository:** domain and daemon logic are independent of SQLite.
- **Command:** daemon protocol operations represent bounded administrative actions.
- **Capability discovery:** adapters describe supported target-selection forms.
- **Data transfer objects / anti-corruption layer:** protocol and UI models do not expose
  provider CLI syntax.
- **Optimistic concurrency:** revision checks prevent lost catalogue updates.
- **Unit of Work:** one SQLite transaction commits a complete catalogue replacement.
- **Adapter:** NordVPN, Mullvad, OpenVPN, and future implementations translate validated
  selectors into their own native operations.

### Rejected alternatives

**SQLite owned or directly writable by the web-service account:** Rejected because a web
process compromise would become direct authoritative catalogue-write access.

**Berkeley DB:** Rejected because it adds native libraries and Python bindings, complicates
locking and recovery, and provides no benefit over SQLite for this small transactional
catalogue.

**Flat mutable YAML as the permanent UI-managed store:** Rejected because conflict detection,
transactional migration, structured provider selectors, and robust recovery would have to be
reimplemented around files.

**One universal provider-target string:** Rejected because it embeds NordVPN's command shape
in the core model and cannot safely express other providers.

**A generic core enumeration of all target kinds:** Rejected because provider semantics differ
and the core would accumulate provider-specific concepts.

**Independent per-entry protocol mutations:** Rejected because add, update, delete, and
reorder requests can create partial state and complicate concurrency.

**Dynamic provider modules or executable database content:** Rejected because database content
must never expand the trusted code base.

**A database server or network SQL service:** Rejected because this catalogue needs one local
writer and no remote database access.

### Consequences

- SQLite becomes a runtime persistence dependency through Python's standard library.
- The privileged daemon gains narrowly scoped configuration-write responsibility.
- The web process remains unprivileged and cannot open the database.
- Provider adapters gain selector validation and schema-metadata responsibilities.
- Protocol and API versions must change where their schemas are incompatible.
- Existing YAML deployments require an explicit migration and rollback procedure.
- Packaging must create and preserve the root-owned database directory without starting a
  partially migrated service.
- Tests must cover SQL failures, corrupt databases, stale revisions, concurrent replacement,
  schema migration, legacy import, permission enforcement, selector validation, provider
  separation, sanitized responses, and daemon restart persistence.
- Documentation must distinguish provider auto-connect from the SnarkyCtl target catalogue.
