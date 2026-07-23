# SnarkyCtl Configuration

SnarkyCtl uses two root-owned, versioned YAML documents. Neither file contains a login password, and neither can select arbitrary Python code or shell commands.

| File | Purpose |
|---|---|
| `/etc/snarkyctl/snarkyctl.yaml` | Interfaces, private HTTPS listener, local control socket, timeouts, provider registry name, and expected upstream interfaces |
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

## Security Properties

- YAML is parsed with the safe loader and each document is limited to 64 KiB.
- The final configuration path may not be a symbolic link and must identify a regular file.
- The provider value is a key in SnarkyCtl's fixed compiled registry. It is not a module or executable name.
- The browser and web service use target aliases only. The root-owned target file maps each alias to its provider value.
- The web listener must equal the address on the private management interface. `0.0.0.0` and the VPS public address cannot pass this relationship check.
- The management, public, and expected upstream VPN interfaces must be distinct.
- Configuration parsing alone does not prove ownership or modes. The future root-level preflight check will require appropriate `root:snarkyctl` or `root:root` ownership and reject group/world-writable authoritative files.

## Schema Evolution

Both documents currently require `schema_version: 1`. SnarkyCtl rejects an unsupported version rather than guessing or rewriting administrator configuration. A future incompatible schema will be introduced explicitly and accompanied by an administrator-run migration procedure.
