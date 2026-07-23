# SnarkyCtl Build and Deployment

## Purpose

This document defines how SnarkyCtl source code becomes a reproducible deployment package for the Ubuntu 24.04 `snarkypuss` gateway.

The deployment model has two artifact layers:

```text
SnarkyCtl source
      │
      ▼
Python wheel
      │
      ▼
Ubuntu/Debian package (.deb)
      │
      ▼
Installed snarkyctl.service
```

The Python wheel is the logical application build artifact. The Debian package is the complete operational artifact installed on the VPS.

The package must be self-contained: installing it on the VPS must not contact PyPI, compile dependencies, rewrite network configuration, or depend on the current state of an external package index.

---

## Deployment Principles

1. **Build once, deploy the same artifact**

   Python dependencies are resolved and assembled during the package build, not during installation on the VPS.

2. **No network-dependent maintainer scripts**

   `postinst` must not run `pip install`, download certificates, clone Git repositories, or retrieve configuration.

3. **Package-owned code is immutable at runtime**

   Application code, the virtual environment, privileged helpers, systemd units, and sudoers policy are owned by `root:root` and are not writable by the `snarkctl` service account.

4. **Local secrets are never build artifacts**

   Password hashes, private keys, certificates, and VPS-specific policy are generated or installed locally and are never committed to Git or embedded in the `.deb`.

5. **Installation does not alter gateway routing**

   Package installation must not connect or disconnect NordVPN, change forwarding, modify firewall rules, expose Direct VPS mode, or reconfigure WireGuard.

6. **Activation is explicit**

   The package may be installed before it is configured. The service is enabled only after configuration, authentication, TLS, and preflight checks succeed.

7. **Configuration survives upgrades**

   Upgrading application code must preserve the authentication file, certificates, target definitions, and administrator settings.

---

## Component Model

| Component | Contents | Runtime privilege | Package treatment |
|---|---|---|---|
| Python application | FastAPI routes, models, parsers, authentication, and policy logic | `snarkctl` | Built as a wheel and installed in the packaged virtual environment |
| Web resources | Jinja2 templates, CSS, and JavaScript | `snarkctl`, read-only | Included as Python package data |
| Privileged helpers | NordVPN and forwarding-mode operations | Root, only through exact sudoers rules | Installed as root-owned executables |
| Service integration | systemd unit, tmpfiles rule, and sudoers policy | System | Installed by the `.deb` |
| Administrator configuration | General settings and approved target labels | Read by `snarkctl` | Installed as examples or conffiles |
| Authentication | Username and salted password hash | Read by `snarkctl` | Generated locally; never included with real credentials |
| TLS identity | Server certificate and private key | Read by service as narrowly permitted | Generated or installed locally |
| Runtime state | Operation lock and transient status | `snarkctl` | Created under `/run/snarkyctl` |
| Persistent state | Minimal policy state, if required | `snarkctl` | Stored under `/var/lib/snarkyctl`; no database |

---

## Proposed Source Layout

```text
snarkyctl/
├── pyproject.toml
├── requirements.lock
├── README.md
├── ARCHITECTURE.md
├── DEPLOYMENT.md
├── INSTALL.md
├── SNARKYCTL.md
│
├── src/
│   └── snarkyctl/
│       ├── __init__.py
│       ├── main.py
│       ├── api.py
│       ├── auth.py
│       ├── commands.py
│       ├── config.py
│       ├── models.py
│       ├── operations.py
│       ├── policy.py
│       ├── static/
│       │   ├── dashboard.js
│       │   └── style.css
│       └── templates/
│           └── index.html
│
├── helpers/
│   ├── snark-nordvpn-connect
│   ├── snark-nordvpn-disconnect
│   ├── snark-mode-direct
│   └── snark-mode-locked
│
├── config/
│   ├── snarkyctl.yaml.example
│   └── targets.yaml.example
│
├── systemd/
│   └── snarkyctl.service
├── sudoers/
│   └── snarkyctl
├── tmpfiles/
│   └── snarkyctl.conf
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── debian/
    ├── changelog
    ├── control
    ├── rules
    ├── conffiles
    ├── postinst
    ├── prerm
    ├── postrm
    └── snarkyctl.install
```

The `src/` layout prevents tests and development commands from accidentally importing Python modules directly from the repository root instead of the built package.

---

## Python Application Artifact

`pyproject.toml` defines the Python project, build backend, package data, and console entry point.

The wheel will have a name such as:

```text
snarkyctl-0.1.0-py3-none-any.whl
```

It contains:

- Python modules.
- Jinja2 templates.
- CSS and JavaScript.
- Package metadata and version.
- A `snarkyctl` command-line entry point.

Example entry-point definition:

```toml
[project.scripts]
snarkyctl = "snarkyctl.cli:main"
```

Planned administrative and diagnostic commands include:

```bash
snarkyctl status
snarkyctl validate-config
snarkyctl preflight
```

The wheel does not contain:

- Live credentials or password hashes.
- TLS private keys or machine certificates.
- VPS-specific routing state.
- sudoers rules.
- systemd installation scripts.

Those are operating-system integration or local-configuration concerns.

---

## Python Dependency Locking

Application dependencies must be locked to exact versions and cryptographic hashes before release. The repository will contain:

```text
requirements.lock
```

The lock file is generated from declared dependencies in `pyproject.toml`. It is reviewed and committed whenever a dependency changes.

The build must fail if:

- A required dependency is not represented in the lock file.
- A downloaded artifact does not match its expected hash.
- Dependency resolution produces an uncommitted lock-file change.
- A dependency cannot be built or retrieved for the target architecture.

No unconstrained `pip install` command is permitted in the release pipeline or Debian maintainer scripts.

---

## Packaged Python Runtime

The Debian package contains a virtual environment assembled during the build. A Debian-oriented builder such as `dh-virtualenv` can create it at the final installation path:

```text
/usr/lib/snarkyctl/venv/
```

This model provides:

- Exact application dependency versions.
- No PyPI access during VPS installation.
- Isolation from Ubuntu's system Python packages.
- A single `.deb` containing the executable application runtime.

If any dependency includes native code, the resulting Debian package is architecture-specific. The first supported target is Ubuntu 24.04 on `amd64`, so the expected package name is:

```text
snarkyctl_0.1.0-1_amd64.deb
```

A future `arm64` package must be built and tested separately.

---

## Installed Filesystem Layout

| Installed path | Purpose | Ownership |
|---|---|---|
| `/usr/lib/snarkyctl/` | Packaged application and virtual environment | `root:root` |
| `/usr/libexec/snarkyctl/` | Privileged helper executables | `root:root` |
| `/etc/snarkyctl/snarkyctl.yaml` | Main administrator configuration | `root:snarkctl`, normally `0640` |
| `/etc/snarkyctl/targets.yaml` | Approved aliases and labels | `root:snarkctl` or `root:root` according to use |
| `/etc/snarkyctl/auth.htpasswd` | Basic-auth username and password hash | `root:snarkctl`, `0640` |
| `/etc/snarkyctl/tls/` | Server certificate and private key | Narrow root/service permissions |
| `/usr/lib/systemd/system/snarkyctl.service` | systemd unit supplied by package | `root:root` |
| `/usr/lib/tmpfiles.d/snarkyctl.conf` | Runtime-directory definition | `root:root` |
| `/etc/sudoers.d/snarkyctl` | Restricted helper authorization | `root:root`, `0440` |
| `/run/snarkyctl/` | Operation lock and ephemeral runtime data | `snarkctl:snarkctl` |
| `/var/lib/snarkyctl/` | Minimal persistent state, if required | `snarkctl:snarkctl` |
| `/usr/share/doc/snarkyctl/` | Packaged documentation and changelog | `root:root` |

`/usr/local` is not used for files owned by the Debian package. It remains reserved for files managed directly by the VPS administrator.

---

## Immutable and Mutable Files

### Immutable package-owned files

These are replaced during an upgrade:

```text
/usr/lib/snarkyctl/
/usr/libexec/snarkyctl/
/usr/lib/systemd/system/snarkyctl.service
/usr/lib/tmpfiles.d/snarkyctl.conf
/etc/sudoers.d/snarkyctl
```

They are owned by `root:root` and are not writable by `snarkctl`.

### Administrator-controlled files

These survive upgrades:

```text
/etc/snarkyctl/snarkyctl.yaml
/etc/snarkyctl/targets.yaml
/etc/snarkyctl/auth.htpasswd
/etc/snarkyctl/tls/
```

The package may install `.example` files for initial configuration. It must never ship real credentials or overwrite locally generated secrets.

### Runtime and persistent state

Operation locks and other ephemeral data belong under:

```text
/run/snarkyctl/
```

If persistent policy state is necessary, it belongs under:

```text
/var/lib/snarkyctl/
```

No database is required. A small file written atomically is sufficient. Direct VPS mode must not be restored automatically after reboot.

Logs go to the systemd journal rather than an application-owned log directory.

---

## Authentication Provisioning

The package creates `/etc/snarkyctl` but does not embed a password or prebuilt auth file.

The administrator creates one interactively:

```bash
sudo htpasswd -cB /etc/snarkyctl/auth.htpasswd snarkadmin
sudo chown root:snarkctl /etc/snarkyctl/auth.htpasswd
sudo chmod 0640 /etc/snarkyctl/auth.htpasswd
```

The password is not placed in:

- Git history.
- The `.deb`.
- Shell command arguments.
- Build logs.
- Environment files.

Changing the password replaces its hash in the local auth file. Package upgrades leave the file untouched.

---

## TLS Provisioning

The Debian package does not contain private keys, a live server certificate, or a private certificate authority.

The configured deployment creates or installs:

```text
/etc/snarkyctl/tls/server.crt
/etc/snarkyctl/tls/server.key
```

The server certificate must include the private hostname used by the Windows browser and may include `10.8.0.1` as an IP Subject Alternative Name.

The private CA should preferably be kept off the VPS after it signs the server certificate. Only the CA certificate is installed in the Windows trusted-root store.

Package upgrades leave the TLS directory untouched.

---

## Debian Package Metadata

The Debian control data will declare operating-system dependencies that must be supplied by Ubuntu, including the required Python runtime and gateway command-line tools. The preassembled virtual environment carries application-level Python dependencies.

The package version has two components:

```text
0.1.0-1
│     └── Debian packaging revision
└──────── upstream SnarkyCtl version
```

The Python package version, command output, wheel metadata, Debian changelog, and release tag must agree on the upstream version.

---

## Maintainer Scripts

Debian lifecycle scripts must remain conservative and idempotent.

### `postinst`

It may:

- Create the non-interactive `snarkctl` system account if absent.
- Create configuration, runtime, and state directories.
- Apply safe ownership and permissions.
- Validate `/etc/sudoers.d/snarkyctl` with `visudo`.
- Run `systemctl daemon-reload`.
- Print the remaining configuration and preflight steps.

It must not:

- Run `pip install` or access PyPI.
- Connect or disconnect NordVPN.
- Change routes, forwarding, DNS, WireGuard, or firewall rules.
- Generate a password automatically.
- Create an unprotected certificate authority.
- enable Direct VPS mode.
- Start a service lacking authentication, configuration, or TLS.

The initial package installs `snarkyctl.service` without automatically enabling it.

### `prerm`

It may stop the service when necessary for removal or upgrade. Upgrade handling should minimize downtime and preserve configuration.

### `postrm`

Normal package removal leaves configuration, authentication, TLS material, and persistent state in place.

Purge behaviour must be explicit. Before deleting locally created credentials or private keys, it should warn the administrator or require those files to be removed separately.

---

## Preflight Activation Gate

After installation and local configuration, the administrator runs:

```bash
sudo snarkyctl preflight
```

The preflight command verifies at least:

- `wg0` exists and owns `10.8.0.1`.
- `nordvpn` and `nordvpnd` are available.
- Required configuration files parse successfully.
- The auth file exists, is readable by `snarkctl`, and is not world-readable.
- The TLS certificate and private key exist and match.
- The certificate covers the configured private hostname or IP address.
- Privileged helpers are root-owned and not writable by `snarkctl`.
- The sudoers file passes `visudo` validation.
- TCP port `8443` is not already occupied.
- No configuration requests binding to `0.0.0.0` or the public VPS address.
- Locked mode can preserve WireGuard management access.

Only after preflight succeeds should the service be activated:

```bash
sudo systemctl enable --now snarkyctl.service
```

---

## Build Pipeline

A release build follows this sequence:

```text
Clean signed or approved source tag
      ↓
Validate version and changelog
      ↓
Verify dependency lock and hashes
      ↓
Run formatting and static checks
      ↓
Run unit tests
      ↓
Build Python wheel
      ↓
Assemble packaged virtual environment
      ↓
Build Debian binary package
      ↓
Run lintian and package-content checks
      ↓
Install into a clean Ubuntu 24.04 test environment
      ↓
Run installation, upgrade, removal, and smoke tests
      ↓
Publish artifacts, checksums, and provenance
```

Representative commands will resemble:

```bash
python3 -m build
dpkg-buildpackage --build=binary --no-sign
lintian ../snarkyctl_*.deb
```

The exact commands will be finalized when `pyproject.toml` and the `debian/` packaging files are implemented.

---

## Test Environments

### Clean Ubuntu container

A container can verify:

- Package dependencies and file placement.
- Ownership and permissions.
- Python imports and CLI execution.
- Configuration validation.
- sudoers syntax.
- Installation, upgrade, removal, and purge behaviour.

A conventional container cannot fully validate systemd, WireGuard, NordVPN, routing, or reboot behaviour.

### Disposable Ubuntu 24.04 VM or VPS

A VM or disposable VPS is required to verify:

- systemd startup and restart behaviour.
- Binding only to the WireGuard address.
- NordVPN CLI integration.
- Routing and firewall transitions.
- Fail-closed Locked mode.
- Explicit Direct VPS mode.
- Reboot behaviour.
- Continued management access during NordVPN transitions.

The live `snarkypuss` gateway should not be the first machine on which a newly built package is installed.

---

## Release Artifacts

A formal release may contain:

```text
snarkyctl_0.1.0-1_amd64.deb
snarkyctl-0.1.0.tar.gz
snarkyctl-0.1.0-py3-none-any.whl
SHA256SUMS
SHA256SUMS.asc
SBOM.spdx.json
```

For personal deployment, the `.deb` is the essential artifact. The wheel and source archive provide traceability and allow the application layer to be inspected independently.

Checksums should be generated from final, immutable release artifacts. If releases are distributed to other users, sign the checksum manifest and publish build provenance.

---

## Installation, Upgrade, and Rollback

Install a locally obtained release with:

```bash
sudo apt-get install ./snarkyctl_0.1.0-1_amd64.deb
```

After configuration and successful preflight:

```bash
sudo systemctl enable --now snarkyctl.service
```

Upgrade with:

```bash
sudo apt-get install ./snarkyctl_0.2.0-1_amd64.deb
```

Rollback using a retained earlier artifact:

```bash
sudo apt-get install ./snarkyctl_0.1.0-1_amd64.deb
```

Application code and package-managed integration files are replaced. Local configuration, authentication, certificates, and permitted persistent state are retained.

Configuration schemas must be versioned. An incompatible version should cause validation or startup to fail clearly rather than silently rewriting administrator configuration.

---

## Removal

Remove the application while retaining local configuration:

```bash
sudo apt-get remove snarkyctl
```

A purge may remove package-supplied configuration, but locally generated credentials and private keys require careful treatment:

```bash
sudo apt-get purge snarkyctl
```

Removal and purge must never modify the gateway's independent WireGuard, NordVPN, DNS, routing, or firewall configuration.

---

## Initial Packaging Milestones

1. Add `pyproject.toml` and the `src/snarkyctl` package skeleton.
2. Add a reproducible dependency-locking process.
3. Build and test the Python wheel.
4. Add systemd, tmpfiles, helper, and sudoers source files.
5. Add Debian metadata and build rules.
6. Produce a `.deb` containing the assembled virtual environment.
7. Test install, upgrade, rollback, remove, and purge in a clean Ubuntu environment.
8. Test the package on a disposable WireGuard/NordVPN gateway.
9. Run preflight and deploy the tested artifact to `snarkypuss`.

The packaging work begins before the dashboard is complete because filesystem ownership, configuration boundaries, command entry points, and service activation rules shape the implementation itself.
