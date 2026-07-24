# Plan 10: Provider-Neutral SQLite Target Catalogue

## Purpose

This plan implements dashboard-managed VPN destinations without coupling SnarkyCtl to
NordVPN or weakening the existing privilege boundary. Destination catalogues will be stored
in SQLite, scoped by provider, validated by compiled provider adapters, and modified only by
the privileged control daemon.

The existing YAML catalogue remains authoritative until the SQLite repository, migration,
verification, and rollback paths have all been implemented and tested. Installation or
upgrade must not silently migrate a deployment.

## Increment 1: Introduce provider-neutral domain models

Add models independent of storage, protocol, and individual VPN providers:

```text
StoredTarget
TargetCatalogue
TargetCatalogueSummary
ProviderTargetSchema
SelectorField
CatalogueRevision
```

A stored target contains:

```text
alias
label
position
selector
```

The catalogue supplies the provider and revision.

Requirements:

- Keep `VpnTarget` and `targets.yaml` working.
- Add no database yet.
- Change no protocol yet.
- Add validation tests for aliases, ordering, selectors, limits, and revisions.

**Checkpoint:** Existing tests and new domain tests pass without changing runtime behavior.

## Increment 2: Extend the provider adapter contract

Extend `VpnProvider` with target capabilities similar to:

```python
def target_schema(self) -> ProviderTargetSchema: ...
def validate_selector(self, selector: JsonObject) -> ValidatedSelector: ...
def import_legacy_target(self, value: str) -> ValidatedSelector: ...
```

Change connection handling conceptually to accept a validated structured target rather than
a raw provider string.

Implement NordVPN selector types:

```text
recommended
country
city
group
server
legacy
```

Examples:

```json
{"kind": "recommended"}
{"kind": "country", "country": "us"}
{"kind": "city", "country": "us", "city": "Dallas"}
{"kind": "server", "server": "us4955"}
```

The temporary `legacy` selector preserves existing `provider_target` values without guessing
their meaning.

**Checkpoint:** NordVPN adapter tests prove that each validated selector produces a fixed
argument array and that malformed or unknown fields are rejected.

## Increment 3: Add the repository abstraction

Introduce:

```python
class TargetRepository(ABC):
    def get_catalogue(self, provider: str) -> TargetCatalogue: ...
    def replace_catalogue(
        self,
        provider: str,
        expected_revision: int,
        targets: tuple[StoredTarget, ...],
    ) -> TargetCatalogue: ...
```

Provide an in-memory implementation for unit tests:

```text
MemoryTargetRepository
```

Move catalogue lookup out of daemon-specific configuration code and behind this interface.
The production daemon continues using a compatibility repository backed by `targets.yaml`.

**Checkpoint:** Daemon tests use the repository interface while the deployed application
behaves exactly as before.

## Increment 4: Implement the SQLite repository

Create:

```text
SqliteTargetRepository
```

Use Python's standard `sqlite3` module with settings including:

```sql
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = ...;
```

Initial tables should cover:

```text
schema_metadata
provider_catalogues
targets
```

Required constraints:

- Unique provider catalogue.
- Unique `(provider, alias)`.
- Unique `(provider, position)`.
- Nonnegative revision.
- Bounded stored JSON.
- Transactional catalogue replacement.

SQL must remain inside the repository implementation.

Tests must cover:

- Empty database initialization.
- Insert and retrieval.
- Ordering.
- Complete replacement.
- Revision increment.
- Stale-revision conflict.
- Duplicate aliases and positions.
- Transaction rollback after failure.
- Two providers with independent catalogues.
- Corrupt or unsupported schemas.
- Database locking and timeout.
- Persistence after process restart.

**Checkpoint:** The SQLite repository passes its tests but is not yet used by production
configuration.

## Increment 5: Add database lifecycle and permissions

Define the canonical location:

```text
/var/lib/snarkyctl/targets.db
```

Implement safe opening and initialization:

- Reject symbolic links.
- Require a regular file.
- Verify root ownership and restrictive permissions.
- Create the database and directory with root-only write access.
- Account for SQLite journal files.
- Refuse unsupported schema versions.
- Run schema migrations transactionally.
- Run an integrity check after initialization or migration.

Add administrative commands such as:

```bash
snarkyctl targets-db initialize
snarkyctl targets-db check
snarkyctl targets-db backup
```

These commands require root when operating on the production path.

**Checkpoint and suggested tag:** Database creation, permissions, integrity checking, and
consistent backup work on a temporary installation tree.

## Increment 6: Extend the control protocol

Add protocol operations:

```text
TARGET_SCHEMA
TARGET_CATALOG_GET
TARGET_CATALOG_REPLACE
```

Add bounded request and response models. `TARGET_CATALOG_REPLACE` contains:

```json
{
  "provider": "nordvpn",
  "expected_revision": 3,
  "targets": []
}
```

Define stable failures:

```text
INVALID_CATALOG
UNKNOWN_PROVIDER
UNSUPPORTED_TARGET_SELECTION
CATALOG_CONFLICT
CATALOG_STORAGE_FAILED
CATALOG_MIGRATION_REQUIRED
```

Increase the maximum protocol-message size only as much as necessary for 100 bounded targets.

**Checkpoint:** Serialization, malformed messages, oversized catalogues, unknown fields, and
version mismatches are fully tested before daemon dispatch is implemented.

## Increment 7: Implement daemon catalogue administration

Connect the new protocol operations to:

- The provider registry.
- Provider selector validation.
- `TargetRepository`.
- The daemon's committed in-memory catalogue.

Replacement sequence:

1. Authenticate the Unix-socket peer.
2. Validate the provider.
3. Validate all core target fields.
4. Ask the adapter to validate every selector.
5. Call `replace_catalogue()`.
6. Replace the in-memory snapshot only after database commit.
7. Return the new revision and sanitized catalogue.

Connection operations continue accepting only an alias:

```text
CONNECT dallas
```

The daemon resolves that alias from the active provider's committed catalogue.

**Checkpoint:** Daemon integration tests cover successful replacement, SQL failure, stale
revisions, provider separation, and continued connection by alias.

## Increment 8: Build the YAML-to-SQLite migration tool

Add an explicit command such as:

```bash
sudo snarkyctl targets-db migrate \
    --config /etc/snarkyctl/snarkyctl.yaml
```

It must:

1. Validate `snarkyctl.yaml` and `targets.yaml`.
2. Determine the configured provider.
3. Back up the YAML and any existing database.
4. Initialize SQLite.
5. Preserve aliases, labels, and order.
6. Pass every legacy provider value to the adapter importer.
7. Abort the whole transaction if any target fails.
8. Verify the resulting catalogue.
9. Print the database revision and migrated count.
10. Leave YAML authoritative until the administrator explicitly changes configuration.

Add a configuration switch resembling:

```yaml
upstream_vpn:
  provider: nordvpn
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
```

The old form remains valid during transition:

```yaml
upstream_vpn:
  provider: nordvpn
  targets_file: /etc/snarkyctl/targets.yaml
```

Do not silently select SQLite merely because the database exists.

**Checkpoint and suggested tag:** Migrate, verify, switch, restart, switch back, and restore
are tested without contacting NordVPN.

## Increment 9: Add control-client and CLI administration

Extend `ControlClient` with operations similar to:

```text
target_schema()
editable_catalogue()
replace_catalogue()
```

Add CLI commands useful for diagnosis and recovery:

```bash
snarkyctl targets list
snarkyctl targets schema
snarkyctl targets export
snarkyctl targets replace FILE
```

Ordinary list output remains sanitized unless an explicitly administrative command is used.
The CLI supports JSON for scripting and UAT.

**Checkpoint:** The complete feature can be operated through the CLI before adding HTTP or
dashboard complexity.

## Increment 10: Add administrative HTTPS endpoints

Add separate endpoints:

```text
GET /api/v3/admin/vpn/target-schema
GET /api/v3/admin/vpn/targets
PUT /api/v3/admin/vpn/targets
```

The replacement endpoint requires:

- HTTP Basic authentication.
- Exact-origin validation.
- `Content-Type: application/json`.
- `X-SnarkyCtl-Request: 1`.
- Expected catalogue revision.
- Complete catalogue replacement.

Keep the ordinary endpoint sanitized:

```text
GET /api/v2/vpn/targets
```

It continues returning only aliases and labels.

**Checkpoint:** API tests verify authentication, request-forgery protections, selector
confidentiality, conflicts, validation failures, and daemon error mapping.

## Increment 11: Build the generic dashboard editor

Add a management section separate from the ordinary connection selector.

The editor must:

- Display the current provider and revision.
- Fetch the provider's selector schema.
- Add destinations.
- Edit labels and selectors.
- Delete destinations with confirmation.
- Reorder destinations.
- Prevent duplicate aliases.
- Prevent an empty catalogue.
- Submit the entire catalogue atomically.
- Display revision conflicts and offer reload rather than overwrite.
- Refresh the ordinary target selector after saving.

The UI may render only reviewed field types:

```text
text
choice
boolean
integer
```

It must not render provider-supplied HTML or execute provider-supplied JavaScript.

**Checkpoint:** Browser tests cover NordVPN forms without embedding NordVPN logic into the
generic editor.

## Increment 12: Packaging, deployment, and UAT

Update:

- `pyproject.toml`
- Debian installation and upgrade scripts
- `INSTALL.md`
- `CONFIGURATION.md`
- `ARCHITECTURE.md`
- `API.md`
- `DEPLOYMENT.md`
- `NORDVPN.md`
- `development/DECISIONS.md`

Package behavior must:

- Preserve `targets.yaml`.
- Preserve an existing database.
- Never migrate automatically.
- Never overwrite a catalogue during upgrade.
- Never start with a partially migrated database.
- Back up before schema migration.
- Preserve root ownership and permissions.

UAT sequence:

1. Install the build without changing the YAML deployment.
2. Initialize and inspect the empty database.
3. Migrate Dallas and Prague.
4. Compare YAML and SQLite catalogue order.
5. Switch configuration to SQLite.
6. Restart the control daemon.
7. Verify dashboard target selection.
8. Add a destination through the editor.
9. Reorder it.
10. Edit its label.
11. Test revision conflict using two browser tabs.
12. Connect to the new destination.
13. Remove a destination.
14. Reboot and verify persistence.
15. Restore the backup and test rollback.
16. Confirm the database cannot be opened by the `snarkyctl` account.
17. Confirm ordinary API responses never expose selector documents.

**Checkpoint and suggested tag:** The packaged feature passes clean-install, upgrade,
migration, rollback, reboot, security, and user-acceptance testing.

## Implementation boundaries

Throughout all increments:

- YAML remains authoritative until explicit migration and configuration switching succeed.
- The web process never opens or writes the SQLite database.
- The privileged daemon is the sole production database reader and writer.
- Provider selectors never become shell fragments.
- Only compiled provider adapters may validate or interpret selectors.
- Ordinary catalogue and status responses never expose provider selector documents.
- Provider auto-connect remains separate from the SnarkyCtl destination catalogue.
- No increment may change routes, firewall state, WireGuard, DNS, or provider connection state
  merely to migrate destination storage.
