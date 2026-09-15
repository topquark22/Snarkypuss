# Documentation Consolidation Plan

## Purpose

This plan consolidates the Snarkypuss documentation into a coherent set of user,
administrator, reference, provider, operations, and development documents.

The repository currently contains strong documentation, but it grew alongside the
implementation. As a result, several documents overlap, some historical material reads as
current guidance, and the ordinary operator does not yet have a dedicated user manual.

The goal is to give every fact one canonical home and make the documentation follow the way
people actually encounter the system:

1. Understand what Snarkypuss is.
2. Build and configure a Snarkypuss gateway.
3. Use it day to day.
4. Diagnose and recover it when something goes wrong.
5. Consult detailed technical references when necessary.
6. Keep planning, design history, and release engineering separate from operator guidance.

This is a documentation project. Source-code changes are out of scope except where a later
documentation finding identifies an implementation or packaging defect that must be handled
as a separate development task.

## Documentation principles

The consolidation will follow these rules:

- Each fact has one canonical home. Other documents link to it rather than duplicating it.
- User documentation describes supported behavior, not unfinished plans.
- Historical requirements and decisions remain available, but are clearly identified as
  historical artifacts.
- Provider-neutral documentation stays provider-neutral. NordVPN- and Mullvad-specific
  procedures live in provider guides.
- Hosting-provider-specific instructions do not become general Snarkypuss requirements.
- Installation guides contain installation and configuration procedures, not release-build
  engineering.
- The user manual assumes an installed system and focuses on ordinary operation.
- Troubleshooting is organized primarily by symptom rather than by subsystem.
- Safety-critical behavior such as Locked mode, Direct VPS mode, leak protection, private
  management access, and reboot persistence is described consistently everywhere.
- Examples must not publish deployment-specific secrets, private keys, credentials, or
  unnecessary private port information.
- Existing formatting and terminology will be preserved where practical; changes should be
  incremental rather than wholesale rewrites.

## Current documentation inventory

### Repository root on `main`

| Document | Current role | Planned disposition |
|---|---|---|
| `README.md` | Project overview, safety model, feature summary, documentation index | Keep at repository root and simplify into the main entry point. |
| `SNARKYPUSS.md` | New scripted gateway workflow combined with an older manual Linode/NordVPN/Windows guide | Split into canonical setup documents, then retire. |
| `INSTALL.md` | SnarkyCtl installation mixed with Python build, manual packaging, and systemd implementation detail | Split administrator installation from development/release material, then retire or replace with a pointer. |
| `CONFIGURATION.md` | SnarkyCtl configuration and destination-catalogue reference | Move to reference documentation with minimal content changes. |
| `ARCHITECTURE.md` | SnarkyCtl software and security architecture | Move to reference documentation and remove unnecessary provider-specific assumptions. |
| `NORDVPN.md` | NordVPN adapter, provider setup, safety behavior, and operational considerations | Move to provider documentation and keep provider-specific material there. |
| `PREFLIGHT.md` | `snarkyctl preflight` reference | Move to reference documentation and reconcile stale implementation statements. |
| `API.md` | Authenticated HTTPS API reference | Move to reference documentation. |
| `DEPLOYMENT.md` | Wheel/Debian build, packaging, deployment artifact, and release-engineering reference | Move to development documentation as build/release material. |

### Existing `development/` documents

| Document | Current role | Planned disposition |
|---|---|---|
| `development/README.md` | Development-artifact index | Keep and update. |
| `development/DECISIONS.md` | Architecture decision record | Keep as historical and current design rationale. |
| `development/PLAN10.md` | Completed SQLite target-catalogue plan | Keep as historical plan. |
| `development/UAT10.md` | Plan 10 acceptance record | Keep as historical UAT record. |
| `development/SNARKYCTL.md` | Earlier SnarkyCtl requirements and roadmap | Archive as historical requirements rather than updating it to look current. |

### Plan 11 material

The `plan11` branch contains Mullvad work that has not yet been integrated into `main`,
including:

- `MULLVAD.md`
- `development/PLAN11.md`
- associated `0.11.0.dev0` implementation and configuration changes

The documentation project must distinguish current `main` behavior from Plan 11 behavior.
Mullvad documentation becomes ordinary provider documentation only when the corresponding
implementation is ready to be treated as supported mainline behavior.

## Target documentation structure

The intended structure is:

```text
README.md

docs/
    USER_MANUAL.md
    SETUP.md

    setup/
        VPS_GATEWAY.md
        WINDOWS_WIREGUARD.md
        SNARKYCTL.md
        LINODE.md

    providers/
        NORDVPN.md
        MULLVAD.md

    operations/
        TROUBLESHOOTING.md
        BACKUP_AND_RECOVERY.md

    reference/
        CONFIGURATION.md
        PREFLIGHT.md
        API.md
        ARCHITECTURE.md

development/
    README.md
    DOC_PLAN.md
    DECISIONS.md
    PLAN10.md
    UAT10.md
    PLAN11.md
    BUILD_AND_RELEASE.md
    archive/
        SNARKYCTL_REQUIREMENTS.md
```

`MULLVAD.md` and `PLAN11.md` appear in the target structure when Plan 11 is merged or its
completed documentation is otherwise incorporated into the mainline documentation set.

## Canonical document responsibilities

### `README.md`

The repository landing page answers:

- What is Snarkypuss?
- What problem does it solve?
- What are the Snarkypuss gateway and SnarkyCtl?
- What are Protected VPN, Locked, Direct VPS, and Unknown states?
- What is the tested/reference deployment?
- Where should a new user go next?

It should remain concise and link to detailed documents rather than becoming another manual.

### `docs/USER_MANUAL.md`

This is the day-to-day operator manual. It assumes Snarkypuss is already installed and
working.

It should cover:

- Opening and authenticating to SnarkyCtl.
- Reading gateway, VPN, public-IP, DNS, and host status.
- Understanding Protected VPN, Locked, Direct VPS, and Unknown states.
- Connecting and switching VPN destinations.
- Managing the destination catalogue through the dashboard.
- Using the Danger Zone safely.
- Normal disconnect and reconnection behavior.
- Expected behavior after reboot.
- Common CLI equivalents for dashboard operations.
- Immediate checks when status is unexpected.
- Links to troubleshooting and reference material for deeper diagnosis.

It should not contain package installation, source builds, or general architecture detail.

### `docs/SETUP.md`

This is the guided installation path. It tells an administrator what to do, in what order,
and links to the detailed setup documents.

The expected flow is:

1. Prepare the VPS and recovery access.
2. Build the private WireGuard gateway.
3. Configure an upstream VPN provider.
4. Configure the Windows WireGuard client.
5. Verify tunnel, DNS, routing, fail-closed behavior, and public egress.
6. Install and configure SnarkyCtl.
7. Run preflight and first-start validation.
8. Perform a reboot/persistence test.
9. Begin normal operation with the user manual.

`SETUP.md` should not repeat every command from the detailed guides.

### `docs/setup/VPS_GATEWAY.md`

This becomes the canonical provider-neutral gateway build and verification guide. It absorbs
the modern scripted portion of `SNARKYPUSS.md`, including:

- Read-only gateway preflight.
- Base package installation.
- Non-secret setup input.
- Generated WireGuard and dnsmasq configuration.
- Migration of an existing manually configured gateway.
- Transactional activation.
- Automatic rollback and confirmation.
- Forwarding and NAT ownership.
- Provider-managed routing boundary.
- Gateway verification.
- Reboot validation where it concerns the base gateway.

Old manual procedures that duplicate the supported generated/transactional workflow should
not remain as an alternative canonical installation path.

### `docs/setup/WINDOWS_WIREGUARD.md`

This becomes the canonical Windows client setup guide. It should cover:

- Installing WireGuard for Windows.
- Generating client keys.
- Supplying the client public key to the gateway setup process.
- Building/importing the client tunnel configuration.
- Tunnel address, DNS, endpoint, `AllowedIPs`, and `PersistentKeepalive`.
- Activating and deactivating the tunnel.
- Optional tunnel-service installation and expected Windows service names.
- Checking handshake and transfer counters.
- Verifying access to the private management address.
- Verifying public IP and DNS after connection.
- Distinguishing WireGuard tunnel success from upstream Internet-routing success.

Windows event-monitoring policy for WireGuard service creation belongs to the separate
Windows monitoring project, not to this guide.

### `docs/setup/SNARKYCTL.md`

This becomes the administrator installation guide for SnarkyCtl. It should contain the
operational parts of the current `INSTALL.md`:

- Supported host prerequisites.
- Installing the supported Debian package.
- Installing/copying configuration examples.
- Initializing the target database.
- Configuring authentication and TLS.
- Validating configuration.
- Running `snarkyctl preflight`.
- Enabling the control socket and web service.
- Performing first-start and first-login checks.
- Verifying service persistence across reboot.
- Upgrade/reinstallation instructions appropriate to an administrator.

Wheel construction, editable installs, build virtual environments, `dh-virtualenv`, linting,
and release packaging belong under development documentation.

### `docs/setup/LINODE.md`

This contains only Linode-specific setup and recovery information:

- Creating an appropriate VPS.
- Recording the public address needed during initial setup.
- Keeping independent console/LISH access available during networking changes.
- Linode Cloud Firewall considerations.
- Recovery access during WireGuard/provider/firewall failures.

Snarkypuss itself must not be described as requiring Linode or a particular Linode region.

### `docs/providers/NORDVPN.md`

This is the canonical home for NordVPN-specific behavior:

- Installing and logging in to the official Linux client.
- NordLynx and other relevant provider settings.
- Firewall and Kill Switch requirements.
- WireGuard-management allowlist/whitelist behavior.
- Provider-specific fail-closed testing.
- Destination selector types and discovery commands.
- NordVPN adapter behavior and limitations.
- NordVPN-specific troubleshooting.

Generic WireGuard, DNS, SnarkyCtl installation, and base gateway instructions should be
linked rather than duplicated.

### `docs/providers/MULLVAD.md`

When Mullvad support becomes mainline, this is the equivalent canonical provider guide. It
should cover only supported Mullvad integration and clearly distinguish manual provider
administration from SnarkyCtl-managed operations.

Until the implementation is ready, Plan 11 documentation remains development material and
must not imply that Mullvad is supported on `main`.

### `docs/operations/TROUBLESHOOTING.md`

Troubleshooting should be organized primarily by symptom. Initial topics should include:

- WireGuard tunnel activates but receives no data.
- WireGuard handshake succeeds but Internet traffic is blocked.
- Internet works but DNS does not.
- SnarkyCtl dashboard is unreachable through the tunnel.
- SSH over the private tunnel is unreachable.
- Provider connection changes break the management path.
- A local VPN client interferes with the Snarkypuss tunnel.
- Services work after manual start but fail after reboot.
- `dnsmasq` starts before the WireGuard address exists.
- Gateway status is `UNKNOWN`.
- Public IP does not match the expected provider exit.
- Locked mode does not appear to block forwarded traffic.
- Direct VPS mode was entered unexpectedly or cannot be exited.

Each symptom should give safe diagnostic commands, expected observations, and links to the
reference/provider document that owns the underlying behavior.

### `docs/operations/BACKUP_AND_RECOVERY.md`

This should consolidate:

- What configuration and state must be backed up.
- Target-database backup and restore.
- WireGuard and DNS configuration backups.
- SnarkyCtl authentication/TLS configuration backup.
- VPS snapshot guidance.
- Activation rollback records and their limits.
- Recovery through the VPS console.
- Recovery after a failed upgrade or provider change.
- Reboot/persistence recovery.

The document should distinguish a consistent application backup from blindly copying a live
SQLite database.

### `docs/reference/CONFIGURATION.md`

This remains the authoritative schema/path/permission reference for:

- Main YAML configuration.
- Provider selection and provider-specific configuration blocks.
- SQLite destination catalogue location and ownership.
- Configuration validation.
- Catalogue administrative CLI operations.
- Backup/restore commands that are specifically part of configuration storage.

Tutorial material should link back to the setup/user documents.

### `docs/reference/PREFLIGHT.md`

This remains the exact reference for `snarkyctl preflight`:

- Purpose and non-mutating behavior.
- Checks performed.
- Result states and exit codes.
- Provider-specific checks.
- Deliberate limitations.

It must be reconciled with the actual current implementation before the documentation
project is considered complete.

### `docs/reference/API.md`

This remains the detailed HTTP API contract, including authentication, hardening, endpoint
schemas, error behavior, and version compatibility.

It should not duplicate user-facing dashboard instructions except where necessary to explain
an API contract.

### `docs/reference/ARCHITECTURE.md`

This is the current technical architecture reference. It should describe:

- Snarkypuss versus SnarkyCtl responsibilities.
- Private client-to-VPS tunnel.
- Provider-owned upstream routing and leak protection.
- Web/control privilege separation.
- Unix-socket protocol boundary.
- Provider adapter boundary.
- Configuration and SQLite ownership.
- systemd/service model.
- Security boundaries and failure modes.

Provider examples are acceptable, but the architecture itself must not assume NordVPN.

### `development/BUILD_AND_RELEASE.md`

This absorbs `DEPLOYMENT.md` and developer-only material currently mixed into `INSTALL.md`:

- Python wheel construction.
- Debian package construction.
- `dh-virtualenv` and dependency locking.
- Build-host requirements.
- Linting/package inspection.
- Source/package filesystem layout.
- Development reinstall helpers.
- Version mapping and release gates.
- Reproducibility requirements.

### `development/archive/SNARKYCTL_REQUIREMENTS.md`

The current `development/SNARKYCTL.md` should be preserved as an historical requirements and
roadmap artifact rather than rewritten to describe current behavior. A short header should
state its historical status and point to the current architecture, user, setup, and decision
documents.

## Known consistency issues to resolve

The consolidation must explicitly audit and resolve at least these known discrepancies:

1. Current `README.md` describes Direct VPS mode, the Danger Zone, and dashboard destination
   editing as implemented, while older reference/development documents still describe some
   of them as unavailable or future work.
2. `development/SNARKYCTL.md` contains historical configuration and scope assumptions that no
   longer match the SQLite catalogue and current dashboard behavior.
3. `SNARKYPUSS.md` contains both the newer generated/transactional gateway workflow and an
   older manual installation workflow.
4. `INSTALL.md` duplicates developer build/package material that belongs with
   `DEPLOYMENT.md`.
5. Architecture and installation text contains NordVPN-specific assumptions in places that
   should now be provider-neutral.
6. Mainline documentation must not claim Mullvad support before the corresponding Plan 11
   implementation is merged and accepted.
7. Version numbers and development-status statements must be checked rather than copied from
   old plans.
8. Commands, service names, paths, configuration keys, API versions, and database locations
   must be checked against the implementation before a document is declared authoritative.

## Work plan

### Phase 1: Establish the documentation skeleton

Create the target `docs/` directory structure and placeholder/index material as needed.
Update `README.md` and `development/README.md` only enough to point readers toward the new
structure while migration is in progress.

**Deliverables:**

- `docs/`, `docs/setup/`, `docs/providers/`, `docs/operations/`, and `docs/reference/`.
- Initial navigation links.
- A clear marker for documents that are temporarily retained during migration.

**Acceptance criteria:**

- No current document is deleted before its useful material has a destination.
- Repository links do not deliberately strand users between old and new documentation.

### Phase 2: Split and retire `SNARKYPUSS.md`

Separate the modern gateway workflow from the older manual walkthrough.

Move/refine material into:

- `docs/SETUP.md`
- `docs/setup/VPS_GATEWAY.md`
- `docs/setup/WINDOWS_WIREGUARD.md`
- `docs/setup/LINODE.md`
- `docs/providers/NORDVPN.md`
- appropriate troubleshooting/recovery documents

Do not preserve duplicate manual procedures merely because they existed historically.
Retain useful explanations and diagnostic material in the appropriate canonical document.

**Acceptance criteria:**

- There is one supported provider-neutral gateway setup path.
- Windows client setup has a clear standalone path.
- Linode-specific instructions are visibly optional/provider-specific.
- `SNARKYPUSS.md` can be removed or reduced to a migration pointer without losing unique
  operational knowledge.

### Phase 3: Create the user manual

Write `docs/USER_MANUAL.md` against actual current behavior.

Use the running dashboard/CLI semantics and current implementation as the authority when old
planning documents disagree.

**Acceptance criteria:**

- A user with an already configured gateway can operate Snarkypuss without reading an
  installation or development document.
- All gateway states and warnings are explained consistently.
- Destination management and Danger Zone behavior match the actual UI.

### Phase 4: Separate SnarkyCtl administration from build engineering

Create `docs/setup/SNARKYCTL.md` from administrator-relevant `INSTALL.md` material.
Move developer/package material into `development/BUILD_AND_RELEASE.md`, using
`DEPLOYMENT.md` as the principal source.

**Acceptance criteria:**

- An administrator can install/configure SnarkyCtl without reading instructions for building
  Python wheels or Debian packages from source.
- A developer/release engineer can build the package without searching through the operator
  installation guide.
- Duplicate procedures are removed or replaced with links.

### Phase 5: Normalize provider documentation

Move and refine NordVPN documentation under `docs/providers/`.
Integrate Mullvad documentation only when the corresponding Plan 11 state is appropriate for
mainline documentation.

**Acceptance criteria:**

- Provider-neutral documents do not contain unnecessary NordVPN assumptions.
- NordVPN-specific leak-protection and management-bypass procedures have one canonical home.
- Mullvad support claims match the implementation branch/release state.

### Phase 6: Create operations and recovery documentation

Build the symptom-oriented troubleshooting guide and consolidated backup/recovery guide from
existing documents and the operational incidents already encountered during development and
use.

**Acceptance criteria:**

- Common tunnel, DNS, provider, management, and reboot failures can be diagnosed without
  reading source code.
- Recovery procedures prefer safe observation before mutation.
- Procedures that can interrupt remote access explicitly require independent console access
  where appropriate.

### Phase 7: Consolidate technical references

Move configuration, preflight, API, and architecture documents into `docs/reference/` and
reconcile them with the current implementation.

This phase should verify facts against source/configuration/systemd files instead of merely
moving Markdown.

**Acceptance criteria:**

- Commands and paths in the reference documents exist in the current code/package.
- Configuration examples match the current schema.
- Preflight documentation matches implemented checks and supported modes.
- API documentation matches implemented routes and request/response models.
- Architecture accurately reflects provider-managed egress and current privilege boundaries.

### Phase 8: Clean up development history

Keep ADRs, plans, and UAT records as historical artifacts. Move build/release engineering
into its own current development document. Archive the old SnarkyCtl requirements/roadmap
without rewriting its historical assertions as though they were current requirements.

Update `development/README.md` to distinguish:

- current development/reference material;
- completed plans and UAT records;
- archived historical requirements.

**Acceptance criteria:**

- Historical documents remain available for design archaeology.
- No historical document is the first place an operator is sent for current instructions.

### Phase 9: Repository-wide consistency and link audit

Perform a final documentation audit after the moves and rewrites.

Check at minimum:

- Relative Markdown links.
- Document indexes/navigation.
- Product naming: Snarkypuss versus SnarkyCtl.
- Gateway-mode terminology.
- Provider-neutral versus provider-specific terminology.
- Paths and file ownership.
- systemd unit names.
- CLI command names and options.
- Configuration keys.
- API route versions.
- Current package/application version statements.
- `main` versus Plan 11 support claims.
- Reboot persistence instructions.
- Leak-protection and Direct VPS warnings.
- Examples for accidental disclosure of credentials, keys, tokens, or deployment-specific
  secrets.

Where practical, add an automated Markdown link check or lightweight documentation test as a
separate development task rather than relying permanently on manual inspection.

**Acceptance criteria:**

- No broken internal Markdown links.
- No two current documents give conflicting instructions for the same operation.
- No historical implementation status is presented as current behavior.
- README navigation reaches every current user/admin/reference document.

### Phase 10: Documentation UAT

Perform a clean read-through from three perspectives:

1. **New administrator:** starts at `README.md` and follows setup through first successful
   protected connection and reboot.
2. **Ordinary user:** starts at `USER_MANUAL.md`, changes destinations, reads status, and
   understands Locked/Direct/Unknown states without consulting development material.
3. **Troubleshooter/developer:** starts from a symptom or technical question and reaches the
   appropriate operations/reference/development document without contradictory guidance.

Record significant UAT findings before declaring the consolidation complete.

**Acceptance criteria:**

- The setup path is complete enough to follow in order.
- Day-to-day operation is understandable without setup internals.
- Troubleshooting paths are discoverable.
- Current references agree with the code and package.
- Development history remains accessible but does not confuse current users.

## Migration strategy

The work should be performed incrementally. During migration:

- Prefer moves and small focused edits over simultaneous rewrites of every document.
- Keep old documents until their unique information has been accounted for.
- Use temporary pointers where necessary to avoid broken links.
- Do not update historical plans merely to make them match the present implementation.
- When a factual discrepancy is discovered, verify the implementation before choosing which
  text to keep.
- Commit documentation changes in logical phases so that individual reorganizations are easy
  to review and revert.

A practical sequence is:

```text
DOC_PLAN.md
    ↓
create docs/ skeleton
    ↓
split SNARKYPUSS.md
    ↓
write USER_MANUAL.md
    ↓
split INSTALL.md / DEPLOYMENT.md
    ↓
normalize provider docs
    ↓
write troubleshooting + recovery
    ↓
move/reconcile references
    ↓
archive/update development docs
    ↓
link + consistency audit
    ↓
documentation UAT
```

## Definition of done

The documentation consolidation is complete when:

- `README.md` is a concise, accurate entry point.
- A complete current `docs/USER_MANUAL.md` exists.
- A new administrator has one clear setup path beginning at `docs/SETUP.md`.
- Gateway, Windows client, SnarkyCtl, hosting-provider, and VPN-provider setup concerns are
  separated cleanly.
- Troubleshooting and recovery have dedicated homes.
- Configuration, preflight, API, and architecture are authoritative references.
- Build and release engineering lives under `development/`.
- Historical plans, ADRs, UAT records, and requirements remain accessible but clearly
  historical where appropriate.
- `SNARKYPUSS.md`, `INSTALL.md`, and `DEPLOYMENT.md` no longer serve overlapping current roles.
- All current documentation agrees on modes, paths, services, provider responsibilities, and
  supported features.
- Internal links have been audited.
- Documentation UAT has been completed and its significant findings resolved.
