# SnarkyCtl Configuration

SnarkyCtl uses a root-owned main YAML document and one explicitly selected target catalogue backend. Existing installations continue using the root-owned `targets.yaml`; SQLite is never selected merely because a database file exists. None of these files contains a login password or can select arbitrary Python code or shell commands.

| File | Purpose |
|---|---|
| `/etc/snarkyctl/snarkyctl.yaml` | Interfaces, private HTTPS listener, local control socket, timeouts, verified public-IP endpoint, provider registry name, and expected upstream interfaces |
| `/etc/snarkyctl/targets.yaml` | Authoritative aliases, display labels, and provider-specific target values |
| `/var/lib/snarkyctl/targets.db` | Optional provider-neutral managed target catalogue |

Examples are supplied as `config/snarkyctl.yaml.example` and `config/targets.yaml.example`.

## Validation

Before starting either service, run:

```bash
sudo snarkyctl validate-config
```

For a staging file or source-tree test:

```bash
snarkyctl validate-config --config ./config/snarkyctl.yaml
```

Success identifies the compiled provider and number of approved targets. Invalid YAML, unknown or extra fields, unsupported schema versions, an unknown provider, unsafe interface relationships, duplicate aliases, relative security-sensitive paths, and a web bind address other than the configured WireGuard management address all cause a nonzero exit.

Validation is deliberately side-effect free. It does not instantiate the provider, contact NordVPN, inspect live interfaces, or alter routing and firewall state. Those live-system checks belong to the later `preflight` command.

## Target Catalogue

The target catalogue is provider-neutral at its public boundary and provider-specific only
inside its root-owned mapping. Every entry has exactly three fields:

| Field | Audience | Meaning |
|---|---|---|
| `alias` | Browser, API, CLI, daemon | Stable provider-neutral identifier such as `dallas` |
| `label` | Browser and human operators | Descriptive text such as `Dallas, United States` |
| `provider_target` | Privileged adapter only | Opaque value understood by the selected provider, such as `Dallas` for NordVPN |

For example:

```yaml
schema_version: 1

targets:
  - alias: dallas
    label: Dallas, United States
    provider_target: Dallas

  - alias: prague
    label: Prague, Czechia
    provider_target: Prague
```

The dashboard receives only `alias` and `label`. When a user selects `dallas`, the
browser sends that alias; the privileged daemon repeats the authoritative lookup and passes
the corresponding `provider_target` to the compiled adapter. The browser cannot submit a
provider command, server name, or arbitrary argument.

The catalogue is therefore generic even though its values are not interchangeable between
providers. An OpenVPN, WireGuard, or future provider adapter may interpret
`provider_target` as a profile identifier, endpoint name, or another constrained value.
Changing providers requires reviewing every provider target; the aliases and labels may
remain stable when they still describe the same user-visible destination.

### Catalogue rules

- Aliases must be unique, begin with a lowercase letter, and contain only lowercase letters,
  digits, underscores, or hyphens. They are API identifiers, so avoid changing them casually.
- Labels must be nonempty and no longer than 100 characters.
- Provider targets must be nonempty and no longer than 200 characters. An adapter may impose
  a narrower syntax.
- The catalogue must contain between 1 and 100 entries.
- Entry order is dashboard order.
- A label must describe the actual scope of its provider target. A country selector such as
  `us` must not be labelled `Dallas`, because the provider may choose another US city.
- Target selection is not a startup or auto-connect policy. For example, NordVPN's bare
  recommended-server auto-connect remains NordVPN configuration rather than a catalogue
  entry.
- No browser choice is written back to this file.

### Add, change, reorder, or remove targets

First make a root-only backup:

```bash
sudo cp -a /etc/snarkyctl/targets.yaml \
    /etc/snarkyctl/targets.yaml.bak
```

Use the installed provider's own read-only discovery commands or documentation to determine
the exact value it accepts. Do not guess a city, country, profile, or server identifier.
Then edit the authoritative file:

```bash
sudoedit /etc/snarkyctl/targets.yaml
```

Add an entry, edit its label or provider value, reorder entries, or remove an entry. Preserve
`schema_version: 1` and the `targets:` list. Restore the required protection and validate
both configuration documents before reloading anything:

```bash
sudo chown root:snarkyctl /etc/snarkyctl/targets.yaml
sudo chmod 0640 /etc/snarkyctl/targets.yaml
sudo /usr/lib/snarkyctl/venv/bin/snarkyctl validate-config \
    --config /etc/snarkyctl/snarkyctl.yaml
```

Validation is read-only. If it fails, correct the file or restore the backup:

```bash
sudo cp -a /etc/snarkyctl/targets.yaml.bak \
    /etc/snarkyctl/targets.yaml
```

After successful validation, restart the privileged daemon so it reloads its immutable
catalogue:

```bash
sudo systemctl restart snarkyctl-control.service
sudo systemctl --no-pager --full status snarkyctl-control.service
```

The socket and web service do not need to be restarted. The dashboard requests the catalogue
from the daemon, so refresh the page after the daemon restart. Verify the sanitized API
response if desired:

```bash
curl --cacert /etc/snarkyctl/tls/ca.crt \
    --user snarkadmin \
    https://10.8.0.1:8443/api/v2/vpn/targets
```

The response must show the new aliases and labels but never the provider targets. Test a new
destination only while independent VPS console access and a second WireGuard management
session are available. Removing the currently selected alias is allowed, but after the reload
the dashboard cannot associate the provider's existing connection with that removed alias.

The daemon remembers the last alias successfully selected through SnarkyCtl only for its
process lifetime. After a daemon restart, or when the provider was changed outside
SnarkyCtl, the alias is deliberately unknown and the dashboard shows **Select a target…**
instead of claiming that the first configured entry is active.

## SQLite Target Backend

SQLite catalogues contain ordered aliases, labels, and structured selectors scoped by provider. Only the privileged daemon opens this database; the web process reaches it only through the bounded Unix-socket protocol.

Migration is an explicit root operation:

```bash
sudo snarkyctl targets-db migrate \
    --config /etc/snarkyctl/snarkyctl.yaml
```

This validates both YAML files, validates every legacy provider value through the compiled adapter, backs up `targets.yaml`, backs up an existing empty database, writes the catalogue as one transaction, and runs an integrity check. It refuses a database containing an existing catalogue. Migration does **not** change `snarkyctl.yaml`, so YAML remains authoritative until the administrator explicitly replaces:

```yaml
upstream_vpn:
  provider: nordvpn
  expected_interfaces: [nordlynx]
  targets_file: /etc/snarkyctl/targets.yaml
```

with:

```yaml
upstream_vpn:
  provider: nordvpn
  expected_interfaces: [nordlynx]
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
```

Then validate and restart the privileged daemon:

```bash
sudo snarkyctl validate-config
sudo snarkyctl targets-db check
sudo systemctl restart snarkyctl-control.service
```

The old YAML form remains the rollback path. Do not configure both forms simultaneously. Administrative lifecycle commands are:

```bash
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
sudo snarkyctl targets-db backup --output /root/targets.db.backup
```

The production directory and database are root-owned with modes `0700` and `0600`. SQLite sidecar journal files inherit the protection of the root-only directory.

## Security Properties

- YAML is parsed with the safe loader and each document is limited to 64 KiB.
- SQLite catalogue changes use complete transactional replacement and optimistic revisions; stale writers cannot silently overwrite a newer catalogue.
- Provider selectors are validated and interpreted only by compiled adapters and are passed to provider commands as fixed argument arrays.
- The final configuration path may not be a symbolic link and must identify a regular file.
- The provider value is a key in SnarkyCtl's fixed compiled registry. It is not a module or executable name.
- The browser and web service use target aliases only. The root-owned target file maps each alias to its provider value.
- The web listener must equal the address on the private management interface. `0.0.0.0` and the VPS public address cannot pass this relationship check.
- The management, public, and expected upstream VPN interfaces must be distinct.
- The public-IP endpoint must use HTTPS without embedded credentials or a URL fragment.
  Certificate and hostname verification always use the operating system trust store.
- Configuration parsing alone does not prove ownership or modes. The root-level preflight
  check requires appropriate `root:snarkyctl` or `root:root` ownership and rejects
  group/world-writable authoritative files.

## Schema Evolution

The YAML documents currently require `schema_version: 1`; the SQLite repository has its own schema version. SnarkyCtl rejects an unsupported version rather than guessing or rewriting administrator data. Database schema migrations are explicit, transactional administrative operations.
