# Snarkypuss Test Suite

## Purpose

The `tests/` directory contains the automated regression suite for the current Snarkypuss and
SnarkyCtl implementation.

These tests are active development tests. They are not obsolete documentation artifacts.
They cover the HTTP API, authentication, command-line client, privileged control daemon,
control protocol, configuration, preflight checks, provider adapters, status collection,
SQLite target storage, gateway scripts, provider setup helpers, packaging, and migration
behavior.

The tests are written for `pytest` and are discovered from `tests/` according to the project
configuration in `pyproject.toml`.

## 1. Test environment

The project currently targets Python 3.12.

A typical local development environment is:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --editable '.[dev]'
```

The `dev` dependency set includes `pytest`, `pytest-cov`, `mypy`, `ruff`, and the other tools
used during development.

## 2. Run the complete test suite

From the repository root:

```bash
.venv/bin/pytest
```

or, when the intended Python environment is already active:

```bash
python -m pytest
```

`pyproject.toml` configures pytest to use:

```text
testpaths = ["tests"]
```

with strict pytest configuration and marker checking enabled.

A successful run means the tests that were collected and executed passed. It does not replace
live VPS acceptance testing, the fail-closed forwarding test, or reboot/persistence testing.

## 3. Run one test module or one test

Examples:

```bash
.venv/bin/pytest tests/test_protocol.py
.venv/bin/pytest tests/test_daemon.py
.venv/bin/pytest tests/test_nordvpn_setup_script.py
.venv/bin/pytest tests/test_api.py::test_interactive_api_documentation_is_disabled
```

Use pytest's normal selection options when isolating a regression.

## 4. Coverage

`pyproject.toml` enables branch coverage for the `snarkyctl` package and defines a coverage
report threshold of 90 percent.

A plain `pytest` run does not itself request coverage collection. To run the suite with
coverage enabled:

```bash
.venv/bin/pytest --cov=snarkyctl --cov-report=term-missing
```

The coverage settings in `pyproject.toml` then apply to the resulting report.

Coverage is useful for finding untested paths, but the percentage is not a substitute for
meaningful safety tests. Gateway-mode transitions, provider failures, protocol validation,
and persistence behavior should be tested explicitly even when line coverage is high.

## 5. Test modules

The current suite is organized by subsystem.

| File | Main coverage |
|---|---|
| `test_api.py` | HTTPS API behavior, authentication boundary, request validation, target administration, and gateway-mode endpoints |
| `test_auth.py` | `htpasswd` credential verification and authentication failures |
| `test_cli.py` | `snarkyctl` command-line behavior and administrative commands |
| `test_client.py` | Unix-socket control client behavior and failures |
| `test_config.py` | Main YAML configuration parsing and validation |
| `test_daemon.py` | Privileged control daemon, target lookup, operation locking, provider failures, and gateway-mode policy |
| `test_gateway_scripts.py` | Gateway configuration, activation, rollback, and verification helpers |
| `test_migration_script.py` | Supported migration from the legacy target representation to the current catalogue model |
| `test_nordvpn_setup_script.py` | NordVPN policy setup helper, allowlist/whitelist compatibility, safety ordering, console confirmation, and documentation integration |
| `test_package.py` | Package/install layout expectations |
| `test_preflight.py` | Read-only deployment preflight checks |
| `test_protocol.py` | Versioned control protocol framing and schema validation |
| `test_providers.py` | Provider abstraction and NordVPN parsing/command behavior |
| `test_status.py` | DNS, system-health, and public-IP status collection |
| `test_target_sqlite.py` | SQLite target repository, revisions, transactions, and integrity behavior |
| `test_targets.py` | Provider-neutral target models and catalogue validation |

Some tests exercise compatibility or migration paths that are no longer the preferred
configuration for new installations. Those tests remain useful while the corresponding
migration or compatibility behavior is still shipped and supported.

## 6. Tests versus live acceptance testing

Most automated tests isolate external systems by using temporary files, fake provider
responses, mock socket interactions, and controlled command results. This makes the suite safe
and repeatable without manipulating the real VPS networking on every run.

Consequently, the automated suite does **not** prove by itself that a deployed gateway:

- establishes a real WireGuard tunnel from Windows;
- preserves private management access during provider changes;
- resolves DNS correctly from the Windows client;
- exits through the intended live VPN provider server;
- blocks forwarded traffic when the provider is disconnected;
- has the intended Linode Cloud Firewall rules; or
- survives an actual reboot with all required services and routes restored.

Those properties require the documented deployment, preflight, fail-closed, and recovery
checks on a real system.

## 7. Current automation status

The repository currently contains the pytest suite and pytest configuration, but does not
contain a GitHub Actions workflow that automatically runs the suite.

The Debian build helper also does not invoke pytest before building the package.

At present, running the tests is therefore an explicit developer/release step rather than an
automatically enforced CI gate.

If automated CI is added later, this document should be updated to describe the authoritative
workflow and any required test matrix.

## 8. Adding or changing tests

When implementation behavior changes:

1. update or add tests in the subsystem that owns the behavior;
2. prefer provider-neutral tests for provider-neutral contracts;
3. keep provider-specific parsing and command expectations in provider tests;
4. test failure paths and unsafe-state rejection, not only successful operations;
5. avoid tests that require the developer's real VPN credentials or live provider account;
6. keep tests deterministic and bounded; and
7. run the relevant module while developing, then the complete suite before treating the
   change as ready.

Documentation-only changes normally do not require application tests unless they expose an
implementation inconsistency that results in a code change.
