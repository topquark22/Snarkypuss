# Plan 11: Mullvad Provider Support

## Purpose

This plan adds Mullvad as the second supported upstream VPN provider and proves that
SnarkyCtl's provider-neutral architecture works beyond NordVPN.

Plan 11 is deliberately limited to Mullvad. OpenVPN and other providers are deferred. A
SnarkyCtl installation selects one compiled provider in root-owned configuration; this plan
does not add simultaneous providers or live switching between providers.

Mullvad continues to own its tunnel, routes, DNS integration, firewall rules, connection
lifecycle, built-in kill switch, and Lockdown mode. SnarkyCtl communicates only through the
reviewed Mullvad command-line interface. It must not manipulate Mullvad routing or reproduce
Mullvad firewall policy.


## Intended result

At completion:

- The trusted provider registry contains both `nordvpn` and `mullvad`.
- Existing NordVPN deployments continue to behave unchanged.
- A root-owned configuration selects exactly one active provider.
- Mullvad destinations are stored in a provider-scoped SQLite catalogue.
- The generic dashboard renders Mullvad destination forms from adapter metadata.
- Connection requests continue to contain only a catalogue alias.
- Protected, Locked, and Direct VPS modes use Mullvad-supported operations.
- Unsupported or unverifiable states fail closed and are reported clearly.
- Installation, preflight, packaging, recovery, and UAT instructions cover Mullvad.


## Non-goals

Plan 11 does not:

- Add OpenVPN support.
- Dynamically load provider plugins or Python modules.
- Run more than one upstream VPN provider at once.
- Switch the configured provider from the browser.
- Store Mullvad account credentials in SnarkyCtl configuration or SQLite.
- Log in to Mullvad on behalf of the administrator.
- Discover or import destinations automatically into the catalogue.
- Implement Mullvad multihop, DAITA, obfuscation, custom DNS, split tunnelling, or account
  management.
- Change Snarkypuss WireGuard, DNS, NAT, or base-gateway ownership.
- Add routes or provider firewall rules directly.


## Design constraints

The accepted architecture remains authoritative:

- Only adapters compiled into the fixed provider registry are trusted.
- The privileged daemon is the only process that invokes provider commands.
- The web service never executes `mullvad` and never opens the target database.
- Provider commands use a fixed executable and argument array with `shell=False`.
- Browser and ordinary API requests identify destinations only by alias.
- Selector documents remain bounded, schema-validated provider data.
- The provider owns routing and fail-closed enforcement.
- Direct VPS mode always requires explicit confirmation and a prominent public-IP warning.
- A provider failure never implies permission to expose the VPS public IP.
- Provider-specific output is untrusted input and must be bounded and parsed defensively.


## Increment 1: Refine the provider contract

Extend the provider-neutral contract only where Mullvad demonstrates a real missing
abstraction.

Add explicit capabilities for the gateway transitions that the UI may offer, such as:

```text
connect
disconnect
target_selection
server_details
leak_protection_configuration
locked_mode
direct_mode
```

The exact model names may differ, but capabilities must distinguish:

- Disconnecting while preserving fail-closed protection.
- Disconnecting while deliberately allowing direct public egress.
- Reading leak-protection state.
- Changing leak-protection state.

Do not infer these operations from the existing generic `disconnect` flag.

Add provider-owned read-only preflight hooks or an equivalent typed result interface. The
core preflight runner must remain responsible for common formatting and severity handling.

Remove assumptions that all providers:

- Select a destination in the same command that initiates connection.
- Report one universal tunnel-interface name.
- Use the term “kill switch.”
- Can expose every safety setting through their CLI.

Preserve the current NordVPN behavior and protocol compatibility.

**Checkpoint:** Contract and model tests pass with NordVPN and the non-mutating placeholder
provider. No Mullvad command is executed yet.


## Increment 2: Add bounded provider-specific configuration

Allow a compiled adapter to receive reviewed provider-specific configuration without
accepting arbitrary commands, executable modules, or free-form options.

A configuration shape may resemble:

```yaml
upstream_vpn:
  provider: mullvad
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
  providers:
    mullvad:
      executable: /usr/bin/mullvad
      service: mullvad-daemon.service
      expected_interfaces:
        - wg0-mullvad
```

The exact default interface expectation must be established from an actual supported
installation before it is documented. It must not be guessed from NordVPN behavior.

Requirements:

- Provider names remain fixed registry identifiers.
- Executable paths are either compiled constants or validated absolute paths from a narrow
  provider-specific field.
- Service names and interface names use strict patterns and bounded lists.
- Unknown provider keys are rejected.
- Configuration for an inactive provider has no runtime effect.
- No account number, password, token, or private key is added to this configuration.
- Existing NordVPN configuration remains valid or receives a documented, mechanically simple
  migration.

The provider factory must receive a typed configuration object rather than only a timeout.

**Checkpoint:** Configuration tests cover NordVPN, Mullvad, unknown providers, unknown fields,
unsafe paths, and provider-specific defaults.


## Increment 3: Implement Mullvad status and settings inspection

Create:

```text
src/snarkyctl/providers/mullvad.py
```

Use the fixed Mullvad executable, expected by default at:

```text
/usr/bin/mullvad
```

Implement a bounded command runner with the same security properties as the NordVPN runner:

- No shell.
- Fixed environment.
- Fixed executable.
- Bounded stdout and stderr.
- Timeout enforcement.
- Controlled errors for missing executable, permission denial, nonzero exit, malformed
  output, and oversized output.

Normalize `mullvad status` into `VpnStatus`, including when observable:

- Disconnected.
- Connecting.
- Connected.
- Disconnecting.
- Error or blocked state.
- Exit relay or server display name.
- Tunnel endpoint details.
- Lockdown or blocking indication.

Inspect Mullvad settings through stable CLI commands and normalize only values that can be
established reliably. A missing or unparseable safety value must become `None` or
`UNKNOWN`, never a favorable assumption.

Keep raw provider output out of ordinary API responses. Bounded diagnostic details may be
returned through existing controlled error handling.

**Checkpoint:** Fixture-driven tests cover representative status and settings output,
localization resistance, malformed fields, new fields, empty output, errors, and size limits.


## Increment 4: Implement Mullvad target schemas

Add Mullvad selector kinds:

```text
recommended
country
city
server
```

Example normalized selectors:

```json
{"kind": "recommended"}
{"kind": "country", "country": "se"}
{"kind": "city", "country": "se", "city": "got"}
{"kind": "server", "country": "se", "city": "got", "server": "se-got-wg-001"}
```

Selector rules must:

- Reject unknown fields.
- Enforce short, provider-appropriate location codes.
- Enforce bounded server identifiers.
- Normalize codes consistently.
- Prevent whitespace, option injection, path syntax, and shell metacharacters where they are
  not part of the reviewed grammar.
- Preserve enough hierarchy to construct an unambiguous Mullvad location operation.
- Avoid a generic legacy selector for new entries.

The generic dashboard must consume the returned schema without Mullvad-specific HTML or
JavaScript.

Changing a target in SQLite changes only approved catalogue data. It does not immediately
change Mullvad state.

**Checkpoint:** Model and adapter tests prove that every accepted selector generates only the
expected fixed argument elements and that malformed selectors are rejected before execution.


## Increment 5: Implement target selection and connection

Mullvad selects a relay separately from starting the connection. The adapter therefore owns
a bounded two-stage operation:

1. Set the reviewed relay selector.
2. Request connection.
3. Poll status for a bounded interval.
4. Return normalized success or a controlled failure.

Conceptual commands are:

```text
mullvad relay set location <country>
mullvad relay set location <country> <city>
mullvad relay set location <country> <city> <server>
mullvad connect
```

A recommended target must explicitly restore Mullvad's automatic/recommended relay selection
using the supported CLI form verified during implementation.

Requirements:

- Never concatenate a command string.
- Do not accept a selector from the browser during connection.
- Resolve the alias from the committed active-provider catalogue.
- Do not modify the catalogue as part of connection.
- Report a relay-selection failure separately from a connection failure.
- Do not report success until the resulting status is connected.
- Preserve Mullvad's selected destination if the connection request fails unless Mullvad's
  documented behavior requires otherwise; document the observed result.
- Do not change Lockdown mode merely to make connection succeed.

**Checkpoint:** Unit and daemon tests cover every selector, command ordering, timeout,
selection failure, connection failure, polling, alias resolution, and status normalization.


## Increment 6: Implement Mullvad gateway-mode transitions

Map SnarkyCtl modes to Mullvad's own controls.

### Protected VPN

The adapter must:

1. Ensure Mullvad Lockdown mode is enabled when the deployment policy requires fail-closed
   protection.
2. Select the requested target.
3. Connect.
4. Verify that Mullvad reports a connected state.
5. Verify safety state where the CLI permits it.

### Locked

The adapter must:

1. Enable Mullvad Lockdown mode.
2. Disconnect Mullvad if necessary.
3. Verify that Mullvad is disconnected or blocked.
4. Verify Lockdown mode is enabled.
5. Never create a public route or disable provider firewall protection.

### Direct VPS

The adapter may offer Direct mode only if it can perform and verify this explicit sequence:

1. Receive the existing server-issued confirmation token.
2. Disable Mullvad Lockdown mode.
3. Disconnect Mullvad.
4. Verify disconnection.
5. Verify Lockdown mode is disabled.
6. Return Direct only when public egress is deliberately allowed.

If any verification is unavailable or ambiguous, return `UNKNOWN` or a controlled failure
rather than claiming Direct or Locked mode.

The Mullvad app's built-in kill switch and optional Lockdown mode are distinct concepts.
SnarkyCtl must use the correct term in user-facing details while continuing to expose the
provider-neutral gateway modes.

Changing provider safety state is transactional at the adapter level as far as Mullvad's CLI
allows. If a multi-command transition fails midway, report the incomplete state clearly and
prefer the safer state where a recovery operation is possible.

**Checkpoint and suggested tag:** Protected, Locked, and Direct transitions pass adapter and
daemon tests without adding routes or firewall commands to SnarkyCtl.


## Increment 7: Register Mullvad and extend preflight

Add `mullvad` to the fixed provider registry. Dynamic imports remain prohibited.

Mullvad preflight must check, without changing system state:

- The executable exists at the configured path.
- The daemon service is installed and active.
- The installed CLI version is supported.
- Root can obtain status.
- Mullvad has already been authenticated by the administrator.
- The configured safety mode can be inspected.
- Expected provider interfaces and management-bypass assumptions are documented and
  observable where practical.
- SQLite contains a valid Mullvad catalogue when Mullvad is active.
- No NordVPN-specific service or interface is required.

Preflight must not:

- Log into a Mullvad account.
- Connect or disconnect.
- Enable or disable Lockdown mode.
- Alter DNS, routes, firewall rules, or interfaces.
- Print account credentials or identifying account material.

Return actionable provider-specific diagnostics while retaining stable core result codes.

**Checkpoint:** Preflight tests cover missing package, inactive daemon, unauthenticated state,
unsupported version, inaccessible CLI, invalid catalogue, and a ready installation.


## Increment 8: Integrate the existing API and dashboard

Use the existing provider-neutral endpoints and catalogue editor. Add new endpoints only if
the current contract genuinely cannot express a required capability.

Verify that the dashboard:

- Displays Mullvad as the active provider.
- Renders country, city, server, and recommended forms from schema metadata.
- Stores and edits a Mullvad provider-scoped catalogue.
- Connects using aliases only.
- Refreshes status after connection.
- Hides operations whose capabilities are false.
- Labels Mullvad Lockdown behavior accurately.
- Keeps the real-public-IP warning prominent for Direct mode.
- Never includes a Mullvad account field.
- Contains no branch such as `if provider == "mullvad"` for selector rendering.

The ordinary target endpoint continues exposing only aliases and labels. Administrative
responses expose validated selector documents only where already authorized by the Plan 10
contract.

**Checkpoint:** API and browser tests use both NordVPN and Mullvad schemas and prove that the
same generic UI path handles both.


## Increment 9: Packaging and systemd integration

Update the Debian packaging without bundling Mullvad itself.

Requirements:

- SnarkyCtl declares Mullvad as an optional external provider, not an unconditional package
  dependency.
- Package installation does not add the Mullvad repository.
- Package installation does not install, authenticate, connect, disconnect, or configure
  Mullvad.
- Upgrades preserve the active provider configuration and every provider-scoped catalogue.
- Provider-specific systemd ordering uses documented administrator-controlled drop-ins where
  required.
- SnarkyCtl services do not acquire a hard dependency on both NordVPN and Mullvad.
- A Mullvad deployment can ensure the provider daemon is available before
  `snarkyctl-control.service` starts.
- Reboot behavior is documented and tested with Mullvad auto-connect and Lockdown policy.
- Clean removal of SnarkyCtl does not remove Mullvad or its account state.

Add build checks confirming that provider documentation is not an executable or packaging
dependency.

**Checkpoint:** The `.deb` builds and installs on a clean test host with Mullvad absent, and
preflight reports the missing optional provider clearly when Mullvad is selected.


## Increment 10: Documentation

Create:

```text
MULLVAD.md
```

Update as necessary:

- `README.md`
- `INSTALL.md`
- `CONFIGURATION.md`
- `ARCHITECTURE.md`
- `API.md`
- `PREFLIGHT.md`
- `DEPLOYMENT.md`
- `development/DECISIONS.md`
- `development/README.md`

Documentation must explain:

- That Mullvad is installed and authenticated independently.
- Which Mullvad versions were tested.
- How to select `provider: mullvad`.
- How to initialize and populate its SQLite catalogue.
- How target selectors map to Mullvad locations.
- The difference between Mullvad's built-in kill switch and Lockdown mode.
- How SnarkyCtl maps Protected, Locked, and Direct modes.
- How to preserve private management access.
- How to configure service ordering and reboot behavior.
- How to diagnose permissions and daemon failures.
- How to return safely to NordVPN through root-owned configuration.
- That provider switching is an administrative restart operation, not a dashboard action.

Do not document OpenVPN as implemented or planned behavior in user-facing guides.


## Increment 11: Automated regression and security testing

Add test coverage for:

- NordVPN behavior remaining unchanged.
- Registry selection for both compiled providers.
- Provider-specific typed configuration.
- Mullvad status parsing and settings inspection.
- Selector validation and command argument construction.
- Multi-command connection sequencing.
- Protected, Locked, and Direct transitions.
- Partial transition failures.
- Unknown and unverifiable states.
- Command timeouts and output limits.
- SQLite catalogue separation between `nordvpn` and `mullvad`.
- Daemon alias resolution under the active provider.
- API capability mapping.
- Generic dashboard rendering.
- Preflight results.
- Package installation without Mullvad.
- Reboot ordering.
- Absence of shell execution, route commands, and firewall commands in the Mullvad adapter.
- Absence of account material in logs, status models, API responses, and SQLite.

Run the complete existing suite as well as the new Mullvad tests.

**Checkpoint:** All automated tests pass for a build that contains both adapters.


## Increment 12: Mullvad UAT

Perform UAT on a VPS with independent console access.

Before testing:

1. Confirm console access.
2. Back up SnarkyCtl configuration and the SQLite target database.
3. Record the working NordVPN configuration.
4. Install Mullvad through its official installation method.
5. Authenticate Mullvad manually.
6. Test Mullvad connection and Lockdown mode independently of SnarkyCtl.
7. Confirm that private management access survives Mullvad transitions.

UAT sequence:

1. Select `mullvad` in root-owned SnarkyCtl configuration.
2. Run preflight and resolve every failure.
3. Initialize or inspect the Mullvad provider catalogue.
4. Add recommended, country, city, and server targets through the dashboard.
5. Restart the control daemon.
6. Verify the catalogue persists and NordVPN targets remain separate.
7. Connect to each Mullvad target.
8. Compare reported status with the Mullvad CLI.
9. Verify observed public egress.
10. Enter Locked mode and confirm public egress is blocked.
11. Confirm private management access remains available while Locked.
12. Enter Direct mode using the explicit confirmation flow.
13. Confirm the UI prominently warns that the VPS public IP is exposed.
14. Return immediately to Protected mode.
15. Test a bad target, unavailable relay, command timeout, and daemon restart.
16. Test a catalogue revision conflict.
17. Reboot in Protected mode and verify service ordering, connection state, catalogue
    persistence, and management access.
18. Reboot in Locked mode and verify fail-closed behavior.
19. Verify the `snarkyctl` service account cannot execute privileged catalogue operations or
    open the database directly.
20. Restore the NordVPN configuration and verify the prior deployment still works.

Record the result in:

```text
development/UAT11.md
```

**Completion checkpoint and suggested tag:** Mullvad passes automated testing, packaging,
reboot testing, rollback testing, security review, and UAT without regressing NordVPN.


## Implementation order

Implement the increments in order. In particular:

- Do not write the Mullvad adapter before the missing provider abstractions are explicit.
- Do not expose Mullvad in the registry before status and failure handling are tested.
- Do not offer Direct mode before its postconditions can be verified.
- Do not perform live provider testing before console access and independent Mullvad testing
  are complete.
- Do not update user-facing documentation to claim Mullvad support until packaged behavior is
  testable.


## References

Implementation must be checked against the Mullvad CLI version actually installed during
development. Useful upstream references include:

- [Mullvad CLI commands for WireGuard](https://mullvad.net/en/help/cli-command-wg)
- [Using the Mullvad VPN app](https://mullvad.net/en/help/using-mullvad-vpn-app)
- [Installing the Mullvad app on Linux](https://mullvad.net/en/help/install-mullvad-app-linux)

Mullvad CLI syntax is an external interface and may change. Tests should record the supported
version range, and preflight must reject or warn about versions that have not been validated.
