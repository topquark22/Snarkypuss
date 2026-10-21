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
| Administrator configuration | Network, service, and provider settings | Read by `snarkyctl` | Installed as an example, then copied and edited locally |
| Authentication | Username and salted password hash | Read by `snarkyctl` | Generated locally; never included with real credentials |
| TLS identity | Server certificate and private key | Read by service as narrowly permitted | Generated or installed locally |
| Runtime state | Control socket and transient status | systemd and `snarkyctl` | Created under `/run/snarkyctl` |
| Persistent state | SQLite target catalogue | Root daemon only | Stored under `/var/lib/snarkyctl/targets.db` |

The dashboard may request a connection using an approved alias, but it cannot execute a
provider command itself. The unprivileged web process validates authentication,
same-origin request metadata, and the public alias before sending a typed request through
the Unix socket. The root daemon performs the authoritative alias lookup and serializes
provider mutations.

---

## Current Source Layout

```text
Snarkypuss/
├── pyproject.toml
├── README.md
├── DEPLOYMENT.md
├── LICENSE
├── docs/                     Numbered setup, configuration, API, and operations guides
├── development/              Design decisions, plans, and acceptance records
├── src/snarkyctl/
│   ├── auth.py
│   ├── cli.py
│   ├── config.py
│   ├── dns_health.py
│   ├── main.py
│   ├── preflight.py
│   ├── status.py
│   ├── control/
│   ├── providers/
│   ├── targets/
│   ├── static/
│   └── templates/
├── config/
│   ├── snarkyctl.yaml.example
│   └── snarkypuss-setup.conf.example
├── scripts/
│   ├── build-deb.sh
│   ├── new-deb-release.sh
│   ├── reinstall-deb.sh
│   ├── legacy/               Archived YAML-to-SQLite migration utilities
│   └── snarkypuss-*          Gateway installation, configuration, and recovery tools
├── systemd/                  Control socket, control daemon, and web service units
├── tests/                    Automated Python regression suite
└── debian/                   Package metadata, rules, lifecycle scripts, and smoke test
```

The `src/` layout prevents tests and development commands from accidentally importing Python modules directly from the repository root instead of the built package.

---

## Python Application Artifact

`pyproject.toml` defines the Python project, build backend, package data, and console entry point.

The wheel will have a name such as:

```text
snarkyctl-2.1.0-py3-none-any.whl
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

A reproducible stable release pipeline must install from the hash-verified lock rather
than resolve dependency ranges. Debian maintainer scripts must never run `pip install`.

The current source version is `2.1.0` (Debian `2.1.0-1`). No
`requirements.lock` is currently checked in or enforced by the build helper. The `dh-virtualenv` build currently
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

- A fixed set of dependency versions inside each built artifact (not yet reproducible
  across separate builds; see dependency locking above).
- No PyPI access during VPS installation.
- Isolation from Ubuntu's system Python packages.
- A single `.deb` containing the executable application runtime.

If any dependency includes native code, the resulting Debian package is architecture-specific. The first supported target is Ubuntu 24.04 on `amd64`, so the expected package name is:

```text
snarkyctl_2.1.0-1_amd64.deb
```

A future `arm64` package must be built and tested separately.

---

## Installed Filesystem Layout

| Installed path | Purpose | Ownership |
|---|---|---|
| `/usr/lib/snarkyctl/` | Packaged application and virtual environment | `root:root` |
| `/usr/bin/snarkyctl` | Link to the packaged command-line entry point | `root:root` |
| `/etc/snarkyctl/snarkyctl.yaml` | Main administrator configuration | `root:snarkyctl`, normally `0640` |
| `/var/lib/snarkyctl/targets.db` | Provider-neutral target catalogue | `root:root`, `0600` |
| `/etc/snarkyctl/auth.htpasswd` | Basic-auth username and password hash | `root:snarkyctl`, `0640` |
| `/etc/snarkyctl/tls/` | Server certificate and private key | Narrow root/service permissions |
| `/usr/lib/systemd/system/snarkyctl-control.socket` | Privileged daemon socket activation | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-control.service` | Privileged control daemon | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-web.service` | Unprivileged HTTPS service | `root:root` |
| `/run/snarkyctl/` | systemd-created runtime socket directory; socket access is `root:snarkyctl`, `0660` | Root-owned directory, `0755` |
| `/var/lib/snarkyctl/` | Target database directory | `root:root`; postinst sets `0700`, control service declares `StateDirectoryMode=0750` |
| `/usr/share/snarkyctl/examples/` | Configuration examples copied by the administrator | `root:root` |
| `/usr/share/doc/snarkyctl/` | Debian-generated package metadata and changelog | `root:root` |

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
/var/lib/snarkyctl/targets.db
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

The SQLite database is application data, not a package-owned conffile. Package installation
creates or corrects the state directory but never initializes, migrates, replaces, or
deletes `targets.db`. Before an upgrade, create a consistent backup with:

```bash
sudo snarkyctl targets-db backup --output /root/targets.db.backup
```

Schema migrations, when introduced, must be explicit, transactional administrative
operations with a backup taken first. Direct VPS mode must not be restored automatically
after reboot.

Logs go to the systemd journal rather than an application-owned log directory.

---

## First-Installation Configuration

Follow [docs/03_SETUP_SNARKYCTL.md](docs/03_SETUP_SNARKYCTL.md) for the complete setup after
WireGuard, gateway DNS, and the upstream VPN provider are configured. On a new installation:

```bash
sudo install -o root -g snarkyctl -m 0640 \
    /usr/share/snarkyctl/examples/snarkyctl.yaml.example \
    /etc/snarkyctl/snarkyctl.yaml
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
```

Do not copy the example over an existing configuration during upgrades. Edit it for the
actual interfaces, management address, provider, and paths, then run
`sudo snarkyctl validate-config`. The database is initialized explicitly, not by package
installation. Manage persisted destinations through the authenticated editor or administrative
CLI; see [docs/08_CONFIGURATION.md](docs/08_CONFIGURATION.md).

The shipped web systemd unit fixes its listener at `10.8.0.1:8443` and its TLS paths in
`ExecStart`. Changing YAML alone does not change Uvicorn's listener. If these values differ,
use a reviewed systemd drop-in that resets and replaces `ExecStart`, then reload systemd;
keep the listener and TLS paths consistent with the YAML and private-only deployment policy.

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

The Debian control data declares Ubuntu dependencies including Python 3.12 or newer,
`adduser`, CA certificates, `iproute2`, systemd, and WireGuard tools. The application itself
requires Python 3.12 (`>=3.12,<3.13`), so use the supported Ubuntu 24.04 runtime. NordVPN
is installed and configured separately. The preassembled virtual environment carries
application-level Python dependencies.

The package version has two components:

```text
2.1.0-1
│     └── Debian packaging revision
└──────── Python upstream version
```

The Python version is `2.1.0`; Debian appends packaging revision `-1` to produce
`2.1.0-1`. Development suffixes map from Python `.devN` to Debian `~devN`,
which sorts before the corresponding stable version. The build helper checks this
mapping. The Python package version, command output, wheel metadata, and Debian upstream
version must agree; the Debian packaging revision is independent.

Repository release tags use `YYYY.MM.DD-N_<snarkyctl-version>`, as documented in
[README.md](README.md#versioning-and-release-tags). They identify a complete Snarkypuss
snapshot rather than simply duplicating the Debian package version.

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

The current preflight implementation checks:

- Configuration schema and the non-interactive `snarkyctl` service identity.
- Ownership and permissions of configuration, database, authentication, and TLS files.
- Configured management and public interfaces, and assignment of the management IPv4 address.
- Availability of the configured private HTTPS bind address and port.
- Authentication-file bcrypt syntax.
- TLS key/certificate matching, certificate expiry, and the management IP address SAN.
- For NordVPN, an executable `/usr/bin/nordvpn` and read-only settings reporting enabled
  Kill Switch and firewall protection.
- Required identity and security directives in the installed systemd units.
- Ownership and permissions of the live control socket, if it exists.

An inactive control socket is reported as `SKIP`. Exposure-policy observation is also
`SKIP`: preflight does not prove fail-closed forwarding, management connectivity during
mode changes, or reboot recovery. It does not comprehensively audit package-code ownership,
verify hostname SANs, or separately verify `nordvpnd` service health. See
[docs/09_PREFLIGHT.md](docs/09_PREFLIGHT.md) for the exact checks and limits.

Run preflight before starting the web service; an already running web service occupies the
port that preflight attempts to bind. Exit status 0 means no `FAIL`, not that every check
returned `PASS`.

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

The sequence above is the release target, not an automated pipeline currently enforced
by the repository. In particular, dependency locking remains outstanding and the Debian
build helper does not run the Python tests or static checks.

On the supported Ubuntu 24.04 amd64 build host, install prerequisites with:

```bash
sudo apt-get install --yes \
    build-essential debhelper devscripts dh-virtualenv lintian \
    python3-dev python3-pip python3-venv
scripts/build-deb.sh
```

The build requires network access while `dh-virtualenv` resolves the development
dependency ranges. Installing the resulting `.deb` does not require PyPI access. A stable
release build will instead consume only artifacts verified by `requirements.lock`.

---

## Build and Deployment Helper Scripts

The following three POSIX shell helpers support package build and deployment. Run them from a checked-out
source tree. All three use `set -eu`, so an unset variable or failed command stops the script
instead of allowing a partial workflow to continue.

### `scripts/build-deb.sh`

This is the repository's supported shortcut for building the Debian binary package:

```bash
scripts/build-deb.sh
```

Run it as the ordinary build user, not with `sudo`. The script accepts no arguments and
automatically changes to the repository root, so it may be invoked from any directory.

Before building, it:

1. Verifies that `dpkg-buildpackage`, `dh`, `dh_virtualenv`, and `lintian` are available.
2. Reads the Python version from `pyproject.toml`.
3. Reads the Debian version from the first entry in `debian/changelog`.
4. Converts a Python development suffix such as `.dev4` to Debian's `~dev4` form.
5. Requires the Debian version to have the same upstream version and a positive numeric
   Debian revision.
6. Requires `LICENSE` and `debian/copyright` to contain identical license text.

For the current release version `2.1.0`, for example, `pyproject.toml` must contain `2.1.0` and the
changelog must begin with a version such as `2.1.0-1`. A mismatch exits with status 2
before `dpkg-buildpackage` runs.

The build and validation commands are:

```bash
dpkg-buildpackage --build=binary --no-sign
lintian --profile debian "../snarkyctl_${debian_version}_amd64.changes"
```

Debian build tools place the resulting package **in the parent directory of the source
checkout**, not in `dist/`. From a checkout named `snarkyctl`, the expected release
artifact is therefore:

```text
../snarkyctl_2.1.0-1_amd64.deb
```

The package currently declares `Architecture: amd64`, and the helper checks the amd64
`.changes` file; build it on the supported amd64 host. Intermediate files may also
be created in the source tree and its parent directory.

The helper validates version and license consistency, builds the package, and runs
`lintian` against its `.changes` file. It does **not** run the Python test suite, type
checker, package installation tests, artifact signing, or publication. Those remain explicit release-pipeline steps.

### `scripts/new-deb-release.sh`

To increment only the Debian packaging revision while retaining the Python version:

```bash
sh scripts/new-deb-release.sh 'Describe the packaging change'
```

The helper requires `dch` (from `devscripts`), `dpkg-parsechangelog`, Python, and `sed`.
It verifies the current Python/Debian version mapping, increments the positive Debian
revision, and writes a new `unstable` entry in `debian/changelog`. Review that tracked
change before building. It does not bump the Python version, create a Git tag, build,
commit, or publish a release.

### `scripts/reinstall-deb.sh`

This helper replaces an already deployed SnarkyCtl package and restarts all three systemd
units:

```bash
sudo scripts/reinstall-deb.sh ../snarkyctl_2.1.0-1_amd64.deb
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
python3.12 -m venv .venv
.venv/bin/python -m pip install --editable '.[dev]'
.venv/bin/pytest
MYPYPATH=src .venv/bin/mypy
.venv/bin/ruff check src tests
.venv/bin/python -m build
scripts/build-deb.sh
sudo scripts/reinstall-deb.sh ../snarkyctl_2.1.0-1_amd64.deb
```

The Python suite runs as an ordinary user; it does not require root or live VPN credentials.
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
snarkyctl_2.1.0-1_amd64.deb
snarkyctl-2.1.0.tar.gz
snarkyctl-2.1.0-py3-none-any.whl
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
sudo apt-get install ./snarkyctl_2.1.0-1_amd64.deb
```

When replacing an installed development build from a source checkout, the guarded helper
performs the stop, reinstall, daemon reload, restart, and status sequence:

```bash
sudo scripts/reinstall-deb.sh ../snarkyctl_2.1.0-1_amd64.deb
```

After configuration and successful preflight:

```bash
sudo systemctl enable --now snarkyctl-control.socket
sudo systemctl enable --now snarkyctl-web.service
```

For upgrades, install the reviewed newer artifact or use `reinstall-deb.sh` for the
explicit stop/restart sequence above. The helper is for an already configured host, not
first-time provisioning.

For rollback, retain the actual previously working artifact and install it explicitly:

```bash
sudo apt-get install --allow-downgrades ./snarkyctl_PREVIOUS_VERSION_amd64.deb
```

Replace `PREVIOUS_VERSION` with the retained version. Stop the SnarkyCtl units before
replacement and restart them after validation; package installation alone does not provide
the helper's explicit restart sequence. Confirm that the retained code supports the current
configuration and database schema. Code rollback does not roll back database contents.

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

## Current Status and Remaining Release Gates

The repository includes Python wheel packaging, Debian build rules, conservative lifecycle
handling, systemd integration, an installed-package smoke test, and build/reinstall helpers.
[development/UAT10.md](development/UAT10.md) records acceptance of the earlier SQLite
catalogue transition; it does not certify every subsequent release.

Before declaring a new release ready:

1. Add and enforce hash-verified dependency locking for reproducible stable builds.
2. Run the Python suite, static checks, and wheel build for the exact release source.
3. Build the `.deb`, run `lintian`, and inspect its contents and dependency requirements.
4. Run the packaged `debian/tests/smoke` check (or the `autopkgtest` smoke test) on an
   installed package; it checks imports, CLI execution, unit files, and the SQLite example,
   not live gateway behavior.
5. Verify installation, upgrade, rollback, removal, and purge on a clean Ubuntu 24.04 host.
6. Validate private access, provider operations, fail-closed forwarding, and reboot recovery
   on a disposable gateway before deploying to the live `snarkypuss` VPS.

The maintainer reports successful testing of SnarkyCtl `2.1.0.dev0` with NordVPN
Linux `6.0.1`. Release `2.1.0` promotes that compatibility work while retaining
NordVPN 5.x backward compatibility and the NordLynx reference transport. This does
not establish support for additional upstream transports. A package build alone
does not establish provider compatibility on a live host.
