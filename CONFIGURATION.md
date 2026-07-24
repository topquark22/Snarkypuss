# SnarkyCtl Configuration

SnarkyCtl uses two root-owned, versioned YAML documents. Neither file contains a login password, and neither can select arbitrary Python code or shell commands.

| File | Purpose |
|---|---|
| `/etc/snarkyctl/snarkyctl.yaml` | Interfaces, private HTTPS listener, local control socket, timeouts, verified public-IP endpoint, provider registry name, and expected upstream interfaces |
| `/etc/snarkyctl/targets.yaml` | Authoritative aliases, display labels, and provider-specific target values |

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

Each target entry contains a public alias, a display label, and one private provider
value. The dashboard retrieves only aliases and labels. Choosing a target sends the alias
back to the web API; the privileged daemon repeats the authoritative lookup and gives the
adapter the corresponding provider value.

Changing the order of entries changes their order in the dashboard selector. Adding or
removing targets requires editing the root-owned file, validating the configuration, and
restarting `snarkyctl-control.service` so the daemon reloads its immutable catalogue.
No target choice is persisted by the browser or written back to configuration.
The daemon remembers the last alias successfully selected through SnarkyCtl for its
process lifetime, allowing status refreshes and page reloads to restore the selector. After
a daemon restart, or when the provider was changed outside SnarkyCtl, the alias is
deliberately unknown and the dashboard shows **Select a target…** instead of claiming that
the first configured entry is active.

## Security Properties

- YAML is parsed with the safe loader and each document is limited to 64 KiB.
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

Both documents currently require `schema_version: 1`. SnarkyCtl rejects an unsupported version rather than guessing or rewriting administrator configuration. A future incompatible schema will be introduced explicitly and accompanied by an administrator-run migration procedure.
