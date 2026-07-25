# SnarkyCtl Configuration

SnarkyCtl uses one root-owned YAML file for service settings and one root-owned SQLite
database for VPN destinations:

| Path | Purpose |
|---|---|
| `/etc/snarkyctl/snarkyctl.yaml` | Interfaces, private HTTPS listener, control socket, timeouts, provider name, and target database location |
| `/var/lib/snarkyctl/targets.db` | Ordered, provider-neutral VPN destination catalogue |

The example main configuration is supplied as `config/snarkyctl.yaml.example`.

## Main configuration

The upstream provider section selects a compiled provider and the SQLite catalogue:

```yaml
upstream_vpn:
  provider: nordvpn
  providers:
    nordvpn:
      executable: /usr/bin/nordvpn
      service: nordvpnd.service
      expected_interfaces:
        - nordlynx
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
```

The provider is a fixed registry name, not a module or executable. Each compiled adapter
accepts only its bounded configuration fields. `expected_interfaces` is an allowlist used
to verify the provider-reported tunnel interface; it is not a command or dynamically loaded
provider setting.

Validate the configuration before starting either service:

```bash
sudo snarkyctl validate-config
```

Validation is side-effect free. It does not connect the VPN or alter routing, DNS, or
firewall state.

## Initialize the target database

The database and its directory are controlled by the privileged daemon and must not be
readable by the unprivileged `snarkyctl` account:

```bash
sudo install -d -o root -g root -m 0700 /var/lib/snarkyctl
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
sudo chown root:root /var/lib/snarkyctl/targets.db
sudo chmod 0600 /var/lib/snarkyctl/targets.db
```

Initialization creates an empty catalogue. After the control socket and web service are
started, open **Manage VPN destinations** in the authenticated dashboard and use
**Add destination** to create the first entry.

## Manage destinations

Each destination contains:

- A stable provider-neutral alias, such as `dallas`.
- A user-facing label, such as `Dallas, United States`.
- A structured selector validated by the active compiled provider adapter.
- An ordering position used by the dashboard.

The dashboard obtains the selector form from the provider schema. It supports only reviewed
field types (`text`, `choice`, `boolean`, and `integer`) and never executes provider-supplied
HTML or JavaScript.

To make changes:

1. Open **Manage VPN destinations**.
2. Add, edit, remove, or reorder entries.
3. Select the provider-defined target type and complete its fields.
4. Select **Save catalogue**.

Saving replaces the complete catalogue atomically. An optimistic revision prevents a stale
browser tab from overwriting a newer change; reload the catalogue when a revision conflict
is reported.

The equivalent administrative CLI workflow is:

```bash
sudo snarkyctl targets list
sudo snarkyctl targets schema
sudo snarkyctl targets export > /root/targets.json
sudoedit /root/targets.json
sudo snarkyctl targets replace /root/targets.json
```

Keep the exported `expected_revision` unchanged when editing. Ordinary catalogue output
contains aliases and labels only; administrative output includes the structured selectors
needed for recovery.

## Backup and recovery

Create a consistent backup through the repository API:

```bash
sudo snarkyctl targets-db check
sudo snarkyctl targets-db backup --output /root/targets.db.backup
sudo chmod 0600 /root/targets.db.backup
```

To restore during a maintenance window:

```bash
sudo systemctl stop snarkyctl-web.service
sudo systemctl stop snarkyctl-control.socket snarkyctl-control.service
sudo install -o root -g root -m 0600 \
    /root/targets.db.backup /var/lib/snarkyctl/targets.db
sudo snarkyctl targets-db check
sudo systemctl start snarkyctl-control.socket
sudo systemctl start snarkyctl-web.service
```

Do not copy a live database directly while it may have SQLite journal files. Use the backup
command.

## Security properties

- Only the privileged daemon opens the database in production.
- `/var/lib/snarkyctl` is `root:root` mode `0700`; `targets.db` is mode `0600`.
- SQLite catalogue replacement is transactional and revision-checked.
- Provider selectors are validated and interpreted only by compiled adapters.
- Provider commands use fixed argument arrays rather than shell fragments.
- The browser submits aliases for ordinary connection requests.
- The ordinary target API never exposes selector documents.
- The web listener must equal the private management-interface address.
- The public-IP endpoint must use verified HTTPS.
- Database schema changes are explicit, transactional administrative operations.

The main YAML document currently requires `schema_version: 1`; the SQLite repository has
its own schema version. Unsupported versions are rejected rather than rewritten implicitly.
