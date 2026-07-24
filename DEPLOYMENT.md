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
Installed SnarkyCtl units
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

   Application code, the virtual environment, and systemd units are owned by `root:root`
   and are not writable by the `snarkyctl` service account.

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
| Python application | FastAPI routes, models, parsers, authentication, and policy logic | `snarkyctl` | Built as a wheel and installed in the packaged virtual environment |
| Web resources | Jinja2 templates, CSS, and JavaScript | `snarkyctl`, unprivileged | Included as Python package data |
| Privileged control daemon | Fixed provider operations and status collection | Root, reached only through the authenticated Unix socket | Included in the Python application and started by systemd socket activation |
| Service integration | Control socket, privileged daemon, and unprivileged web units | System | Installed by the `.deb` but not enabled or started automatically |
| Administrator configuration | General settings and approved target labels | Read by `snarkyctl` | Installed as examples, then copied and edited locally |
| Authentication | Username and salted password hash | Read by `snarkyctl` | Generated locally; never included with real credentials |
| TLS identity | Server certificate and private key | Read by service as narrowly permitted | Generated or installed locally |
| Runtime state | Control socket and transient status | systemd and `snarkyctl` | Created under `/run/snarkyctl` |
| Persistent state | Provider CLI home and minimal state, if required | Root daemon or `snarkyctl`, as applicable | Stored under `/var/lib/snarkyctl`; no database |

The dashboard may request a connection using an approved alias, but it cannot execute a
provider command itself. The unprivileged web process validates authentication,
same-origin request metadata, and the public alias before sending a typed request through
the Unix socket. The root daemon performs the authoritative alias lookup and serializes
provider mutations.

---

## Current Source Layout

The following tree reflects the tracked source and documentation at release 0.9.0.
Generated build directories, Python caches, and Debian build artifacts are not shown.

```text
snarkyctl/
├── API.md
├── ARCHITECTURE.md
├── CONFIGURATION.md
├── DEPLOYMENT.md
├── INSTALL.md
├── NORDVPN.md
├── PREFLIGHT.md
├── README.md
├── SNARKYPUSS.md
├── deploy.sh
├── pyproject.toml
│
├── config/
│   ├── snarkyctl.yaml.example
│   ├── snarkypuss-setup.conf.example
│   └── targets.yaml.example
│
├── development/
│   ├── README.md
│   ├── SNARKYCTL.md
│   └── DECISIONS.md
│
├── scripts/
│   ├── build-deb.sh
│   ├── reinstall-deb.sh
│   ├── snarkypuss-activate.py
│   ├── snarkypuss-configure.py
│   ├── snarkypuss-install.sh
│   ├── snarkypuss-migrate.py
│   ├── snarkypuss-rollback.py
│   ├── snarkypuss-preflight.sh
│   └── snarkypuss-verify.sh
│
├── src/
│   └── snarkyctl/
│       ├── __init__.py
│       ├── auth.py
│       ├── cli.py
│       ├── config.py
│       ├── main.py
│       ├── preflight.py
│       ├── status.py
│       ├── control/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── daemon.py
│       │   └── protocol.py
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── nordvpn.py
│       │   ├── placeholder.py
│       │   └── registry.py
│       ├── static/
│       │   ├── dashboard.css
│       │   └── dashboard.js
│       └── templates/
│           └── dashboard.html
│
├── systemd/
│   ├── snarkyctl-control.service
│   ├── snarkyctl-control.socket
│   └── snarkyctl-web.service
│
├── tests/
│   ├── test_api.py
│   ├── test_auth.py
│   ├── test_cli.py
│   ├── test_client.py
│   ├── test_config.py
│   ├── test_daemon.py
│   ├── test_gateway_scripts.py
│   ├── test_migration_script.py
│   ├── test_package.py
│   ├── test_preflight.py
│   ├── test_protocol.py
│   ├── test_providers.py
│   └── test_status.py
│
└── debian/
    ├── README.Debian
    ├── changelog
    ├── control
    ├── copyright
    ├── postinst
    ├── rules
    ├── snarkyctl.install
    ├── snarkyctl.links
    ├── source/
    │   └── format
    └── tests/
        ├── control
        └── smoke
```

The `src/` layout prevents tests and development commands from accidentally importing
Python modules directly from the repository root instead of the built package. The
`scripts/` helpers provide the guarded Debian build and reinstall workflows documented
under [Build and Deployment Helper Scripts](#build-and-deployment-helper-scripts).

---

## Python Application Artifact

`pyproject.toml` defines the Python project, build backend, package data, and console entry point.

The wheel will have a name such as:

```text
snarkyctl-0.9.0-py3-none-any.whl
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

Administrative and diagnostic commands include:

```bash
snarkyctl status
snarkyctl connect dallas
snarkyctl disconnect
snarkyctl validate-config
snarkyctl preflight
```

The wheel does not contain:

- Live credentials or password hashes.
- TLS private keys or machine certificates.
- VPS-specific routing state.
- systemd installation scripts.

Those are operating-system integration or local-configuration concerns.

---

## Python Dependency Locking

Application dependencies must be locked to exact versions and cryptographic hashes before
a stable release. The intended repository artifact is:

```text
requirements.lock
```

The lock file is generated from declared dependencies in `pyproject.toml`. It is reviewed and committed whenever a dependency changes.

The build must fail if:

- A required dependency is not represented in the lock file.
- A downloaded artifact does not match its expected hash.
- Dependency resolution produces an uncommitted lock-file change.
- A dependency cannot be built or retrieved for the target architecture.

No unconstrained `pip install` command is permitted in the stable release pipeline or
Debian maintainer scripts.

The `0.9.0` package is a development package. Its `dh-virtualenv` build currently
resolves the bounded dependency ranges from `pyproject.toml` while assembling the package.
This never causes package installation to contact PyPI, but it is not yet a reproducible
release build. Adding and enforcing the hashed lock file remains a release gate.

---

## Packaged Python Runtime

The Debian package contains a virtual environment assembled during the build.
`dh-virtualenv` creates it at the final installation path:

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
snarkyctl_0.9.0-1_amd64.deb
```

A future `arm64` package must be built and tested separately.

---

## Installed Filesystem Layout

| Installed path | Purpose | Ownership |
|---|---|---|
| `/usr/lib/snarkyctl/` | Packaged application and virtual environment | `root:root` |
| `/usr/bin/snarkyctl` | Link to the packaged command-line entry point | `root:root` |
| `/etc/snarkyctl/snarkyctl.yaml` | Main administrator configuration | `root:snarkyctl`, normally `0640` |
| `/etc/snarkyctl/targets.yaml` | Approved aliases and labels | `root:snarkyctl`, normally `0640` |
| `/etc/snarkyctl/auth.htpasswd` | Basic-auth username and password hash | `root:snarkyctl`, `0640` |
| `/etc/snarkyctl/tls/` | Server certificate and private key | Narrow root/service permissions |
| `/usr/lib/systemd/system/snarkyctl-control.socket` | Privileged daemon socket activation | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-control.service` | Privileged control daemon | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-web.service` | Unprivileged HTTPS service | `root:root` |
| `/run/snarkyctl/` | systemd-created runtime socket directory | `root:snarkyctl` |
| `/var/lib/snarkyctl/` | Provider CLI home and minimal persistent state | `snarkyctl:snarkyctl` initially; systemd may manage service ownership |
| `/usr/share/doc/snarkyctl/examples/` | Configuration examples copied by the administrator | `root:root` |
| `/usr/share/doc/snarkyctl/` | Packaged documentation and changelog | `root:root` |

`/usr/local` is not used for files owned by the Debian package. It remains reserved for files managed directly by the VPS administrator.

---

## Immutable and Mutable Files

### Immutable package-owned files

These are replaced during an upgrade:

```text
/usr/lib/snarkyctl/
/usr/bin/snarkyctl
/usr/lib/systemd/system/snarkyctl-control.socket
/usr/lib/systemd/system/snarkyctl-control.service
/usr/lib/systemd/system/snarkyctl-web.service
```

They are owned by `root:root` and are not writable by `snarkyctl`.

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
sudo chown root:snarkyctl /etc/snarkyctl/auth.htpasswd
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
0.9.0-1
│          └── Debian packaging revision
└───────────── PEP 440 development version mapped for Debian ordering
```

PEP 440 spells the current version `0.9.0`; Debian spells it
`0.9.0-1` so it sorts before a future `0.1.0-1`. The build helper checks this
mapping. The Python package version, command output, wheel metadata, Debian changelog, and
release tag must otherwise agree.

---

## Maintainer Scripts

Debian lifecycle scripts must remain conservative and idempotent.

### `postinst`

It may:

- Create the non-interactive `snarkyctl` system account and group if absent.
- Create configuration, TLS, and state directories.
- Apply safe ownership and permissions.
- Allow debhelper to reload systemd metadata.

It must not:

- Run `pip install` or access PyPI.
- Connect or disconnect NordVPN.
- Change routes, forwarding, DNS, WireGuard, or firewall rules.
- Generate a password automatically.
- Create an unprotected certificate authority.
- Enable direct VPS mode.
- Start a service lacking authentication, configuration, or TLS.

The package installs all three units without automatically enabling or starting them.

Debhelper generates the standard systemd removal and upgrade handling. Normal package
removal leaves locally created configuration, authentication, TLS material, and persistent
state in place. Purge intentionally does not delete locally generated credentials or
private keys.

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
- The auth file exists, is readable by `snarkyctl`, and is not world-readable.
- The TLS certificate and private key exist and match.
- The certificate covers the configured private hostname or IP address.
- Package-owned code and units are root-owned and not writable by `snarkyctl`.
- The control socket is owned by `root:snarkyctl` and is not accessible to other users.
- TCP port `8443` is not already occupied.
- No configuration requests binding to `0.0.0.0` or the public VPS address.
- Locked mode can preserve WireGuard management access.

Only after preflight succeeds should the service be activated:

```bash
sudo systemctl enable --now snarkyctl-control.socket
sudo systemctl enable --now snarkyctl-web.service
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
sudo apt-get install --yes \
    build-essential debhelper devscripts dh-virtualenv lintian \
    python3-dev python3-pip python3-venv
scripts/build-deb.sh
lintian ../snarkyctl_*.deb
```

The build requires network access while `dh-virtualenv` resolves the development
dependency ranges. Installing the resulting `.deb` does not require PyPI access. A stable
release build will instead consume only artifacts verified by `requirements.lock`.

---

## Build and Deployment Helper Scripts

The `scripts/` directory contains two POSIX shell helpers. Run them from a checked-out
source tree. Both use `set -eu`, so an unset variable or failed command stops the script
instead of allowing a partial workflow to continue.

### `scripts/build-deb.sh`

This is the repository's supported shortcut for building the Debian binary package:

```bash
scripts/build-deb.sh
```

Run it as the ordinary build user, not with `sudo`. The script accepts no arguments and
automatically changes to the repository root, so it may be invoked from any directory.

Before building, it:

1. Verifies that `dpkg-buildpackage`, `dh`, and `dh_virtualenv` are available.
2. Reads the Python version from `pyproject.toml`.
3. Reads the Debian version from the first entry in `debian/changelog`.
4. Converts a Python development suffix such as `.dev4` to Debian's `~dev4` form.
5. Requires the Debian version to have the same upstream version and a positive numeric
   Debian revision.

For release `0.9.0`, for example, `pyproject.toml` must contain `0.9.0` and the
changelog must begin with a version such as `0.9.0-1`. A mismatch exits with status 2
before `dpkg-buildpackage` runs.

The final command is:

```bash
dpkg-buildpackage --build=binary --no-sign
```

Debian build tools place the resulting package **in the parent directory of the source
checkout**, not in `dist/`. From a checkout named `snarkyctl`, the expected release
artifact is therefore:

```text
../snarkyctl_0.9.0-1_amd64.deb
```

The exact architecture is determined by the build environment. Intermediate files may also
be created in the source tree and its parent directory.

The helper validates version consistency and builds the package. It does **not** run the
Python test suite, type checker, `lintian`, package installation tests, artifact signing, or
publication. Those remain explicit release-pipeline steps.

### `scripts/reinstall-deb.sh`

This helper replaces an already deployed SnarkyCtl package and restarts all three systemd
units:

```bash
sudo scripts/reinstall-deb.sh ../snarkyctl_0.9.0-1_amd64.deb
```

It must run as root and accepts exactly one argument: the path to a regular `.deb` file.
Before stopping anything, it verifies that:

- `apt-get`, `dpkg-deb`, and `systemctl` are available.
- The argument names an existing regular file.
- The package's embedded `Package` field is exactly `snarkyctl`.

It then performs this sequence:

1. Stops `snarkyctl-web.service`.
2. Stops `snarkyctl-control.service`.
3. Stops `snarkyctl-control.socket`.
4. Runs `apt-get install --yes --reinstall` with the absolute package path.
5. Reloads systemd.
6. Starts the control socket, control service, and web service.
7. Requires all three units to report an active state.
8. Prints their complete status.

The script intentionally uses `start`, not `enable`; it does not change boot-time
enablement policy. It also does not edit configuration, generate credentials or TLS
certificates, run preflight, back up local state, or automatically reinstall an older
package after failure.

If installation or restart fails, the script exits immediately and warns that services may
remain stopped. Inspect the preceding error and unit logs before manually starting them.
Because there is no automatic rollback, retain the previously working `.deb`.

### Recommended local release sequence

From the repository root:

```bash
python3 -m pytest
python3 -m mypy src
scripts/build-deb.sh
lintian ../snarkyctl_0.9.0-1_amd64.deb
sudo scripts/reinstall-deb.sh ../snarkyctl_0.9.0-1_amd64.deb
```

Use the project's virtual-environment executables instead of `python3 -m` where applicable.
Perform the reinstall first on a disposable Ubuntu 24.04 system; the live gateway should not
be the first package-installation test.

---

## Test Environments

### Clean Ubuntu container

A container can verify:

- Package dependencies and file placement.
- Ownership and permissions.
- Python imports and CLI execution.
- Configuration validation.
- systemd unit syntax and activation policy.
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
snarkyctl_0.9.0-1_amd64.deb
snarkyctl-0.9.0.tar.gz
snarkyctl-0.9.0-py3-none-any.whl
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
sudo apt-get install ./snarkyctl_0.9.0-1_amd64.deb
```

When replacing an installed development build from a source checkout, the guarded helper
performs the stop, reinstall, daemon reload, restart, and status sequence:

```bash
sudo scripts/reinstall-deb.sh ../snarkyctl_0.9.0-1_amd64.deb
```

After configuration and successful preflight:

```bash
sudo systemctl enable --now snarkyctl-control.socket
sudo systemctl enable --now snarkyctl-web.service
```

Upgrade with:

```bash
sudo apt-get install ./snarkyctl_0.9.1-1_amd64.deb
```

Rollback using a retained earlier artifact:

```bash
sudo apt-get install ./snarkyctl_0.9.0-1_amd64.deb
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

1. ~~Add `pyproject.toml` and the `src/snarkyctl` package skeleton.~~
2. Add a reproducible, hash-verified dependency-locking process.
3. ~~Build and test the Python wheel.~~
4. ~~Add the socket, privileged daemon, and web systemd units.~~
5. ~~Add Debian metadata, lifecycle handling, smoke test, and build rules.~~
6. Produce and inspect a `.deb` containing the assembled virtual environment.
7. Test install, upgrade, rollback, remove, and purge in a clean Ubuntu environment.
8. Test the package on a disposable VPN gateway.
9. Run preflight and deploy the tested artifact to `snarkypuss`.

The packaging work begins before the dashboard is complete because filesystem ownership, configuration boundaries, command entry points, and service activation rules shape the implementation itself.
