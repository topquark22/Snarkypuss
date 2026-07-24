# SnarkyCtl Configuration

SnarkyCtl uses a root-owned main YAML document and one explicitly selected target
catalogue backend. Existing installations continue using the root-owned `targets.yaml`;
SQLite is available for the managed catalogue but is never selected merely because a
database file exists. None of these files contains a login password or can select arbitrary
Python code or shell commands.

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

### Existing YAML backend

Each target entry contains a public alias, a display label, and one private provider
value. The dashboard retrieves only aliases and labels. Choosing a target sends the alias
back to the web API; the privileged daemon repeats the authoritative lookup and gives the
adapter the corresponding provider value.

Changing the order of entries changes their order in the dashboard selector. Adding or
removing targets requires editing the root-owned file, validating the configuration, and
restarting `snarkyctl-control.service` so the daemon reloads its immutable catalogue.
No target choice is persisted by the browser or written back to configuration.

The target catalogue also reports provider capabilities. The dashboard enables its
advanced gateway modes only when the compiled adapter supports connect, disconnect, and
leak-protection configuration as required. Capabilities cannot be enabled through YAML.

### SQLite backend

SQLite catalogues contain ordered aliases, labels, and structured selectors scoped by
provider. Only the privileged daemon opens this database. The web process reaches it only
through the bounded Unix-socket protocol.

Migration is an explicit root operation:

```bash
sudo snarkyctl targets-db migrate \
    --config /etc/snarkyctl/snarkyctl.yaml
```

This validates both YAML files, validates every legacy provider value through the compiled
adapter, backs up `targets.yaml`, backs up an existing empty database, writes the catalogue
as one transaction, and runs an integrity check. It refuses a database containing an
existing catalogue. The resulting catalogue begins at revision 1.

Migration does **not** change `snarkyctl.yaml`. YAML therefore remains authoritative until
the administrator replaces:

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

The old YAML form remains the rollback path: restore `targets_file`, validate, and restart.
Do not configure both forms simultaneously.

Administrative lifecycle commands are:

```bash
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
sudo snarkyctl targets-db backup --output /root/targets.db.backup
```

The production directory and database are root-owned with modes `0700` and `0600`.
SQLite sidecar journal files inherit the protection of the root-only directory.

## Security Properties

- YAML is parsed with the safe loader and each document is limited to 64 KiB.
- SQLite catalogue changes use complete transactional replacement and optimistic revisions;
  stale writers cannot silently overwrite a newer catalogue.
- Provider selectors are validated and interpreted only by compiled adapters and are always
  passed to provider commands as fixed argument arrays.
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

The YAML documents currently require `schema_version: 1`; the SQLite repository has its own
schema version. SnarkyCtl rejects an unsupported version rather than guessing or rewriting
administrator data. Database schema migrations are explicit, transactional administrative
operations.
