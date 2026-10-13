# Multi-Protocol VPN Support Project Plan

## Purpose

This plan describes a future, provider-neutral extension of Snarkypuss and SnarkyCtl to
support multiple upstream VPN transport protocols without weakening gateway safety.

NordVPN provides the immediate motivation: NordLynx is the current reference transport,
while NordVPN 6.x introduces a unified protocol setting and NordWhisper for restrictive
networks. OpenVPN TCP/UDP are other possible NordVPN transports. Mullvad may expose its own
supported protocol choices. The available protocols and their actual network behavior must
be discovered and validated against installed provider clients, not assumed here.

**This is planning only. No multi-protocol implementation begins until the work on
`nordvpn-6` is completely validated and merged into `main`.** In particular, the existing
NordLynx-only reference deployment remains the production baseline until a later,
separately tested change is approved.

## Prerequisites and sequencing

Before starting this plan:

1. Complete the NordVPN 5.x backward-compatibility review and regression tests for
   `nordvpn-6`, including the production 5.4.1 command behavior.
2. Validate NordVPN 6.x on an isolated test Linode when the client is available, including
   command syntax, status/settings output, routing, DNS, management access, and fail-closed
   forwarding with NordLynx.
3. Resolve the documentation differences between `main` and `nordvpn-6`; merge and close
   the compatibility PR.
4. Establish a known-good baseline on `main` and record actual provider CLI responses,
   network-interface names, route/policy-routing behavior, and Kill Switch behavior.
5. Create a separate development branch for this project only after the preceding gates pass.

A passing mocked test suite alone is not sufficient to declare the NordVPN 6.x prerequisite
validated. Do not experiment with new transports on the production gateway.

## Principles

- Keep provider-specific protocol selection inside the trusted provider adapter.
- Keep the browser, HTTP API, control protocol, and persistent catalogue provider-neutral.
- Preserve the privilege separation between the unprivileged web service and root control
  daemon. Never accept arbitrary CLI commands or provider arguments from the browser.
- The provider owns tunnel creation, routes, DNS integration, and its own Kill Switch/firewall
  policy. Snarkypuss must not create a competing provider-routing authority.
- Separate the provider identity, selected transport, observed egress interface, and verified
  gateway protection state. None is interchangeable with another.
- Do not treat a provider's `Connected` status or claimed transport as proof that forwarded
  Windows traffic is protected.
- Unknown, missing, contradictory, or stale protection evidence must never be promoted to
  Protected VPN; never fall back silently to Direct VPS.
- Preserve the private WireGuard management path and independent Linode LISH recovery path.
- Keep NordLynx the default reference transport unless a later explicit decision changes it.
- Preserve existing target records and their selection intent wherever possible.

## Non-goals

This project will not:

- replace the Windows-to-Linode WireGuard tunnel;
- implement NordWhisper, OpenVPN, or WireGuard protocol engines inside SnarkyCtl;
- make every provider support every transport;
- allow user-supplied command fragments, device names, route rules, or shell execution;
- automatically switch protocols in response to a failed connection;
- disable provider leak protection merely to make a new transport work;
- merge transport selection into destination selection without a separately reviewed model;
- promise censorship resistance, anonymity, or uniform behavior across providers.

## Phase 1: Observe and document the current safety boundary

Review `VpnProvider`, `VpnStatus`, `VpnSettings`, provider adapters, config, preflight,
control daemon, gateway scripts, and documentation. Identify every assumption involving
`nordlynx`, the current `technology` field, `expected_interfaces`, interface inference,
provider routing ownership, and gateway-mode classification.

Record which evidence comes from provider-reported output versus independent operating-system
observations. Capture a read-only baseline for each tested transport, without saving credentials
or private keys. Decide which safety observations are actually reliable before designing new
fields.

### Phase 1 acceptance criteria

- The review identifies every transport-dependent assumption and its security consequence.
- Provider-owned routing and Snarkypuss-owned gateway forwarding remain clearly separated.
- The existing NordLynx deployment and fail-closed behavior are documented as the baseline.

## Phase 2: Provider-neutral transport model

Design a small, explicit capability for providers that support transport discovery or
selection. Candidate concepts include a stable transport identifier, provider-specific
variants, display label, supported selections, and observed active transport. These are
design candidates, not committed API names.

Keep selected transport policy distinct from observed connection state and from the actual
egress interface. Define validation, unsupported-capability behavior, and how absent or
unknown transport data is represented. Determine whether configuration needs persistence
and, if so, design a non-destructive migration with a NordLynx-compatible default.

### Phase 2 acceptance criteria

- Providers without transport selection work unchanged.
- Existing stored destination selectors retain their meaning.
- Unknown or unsupported transports cannot be selected by arbitrary strings.
- Changes to schemas, control messages, or persistence are explicit and versioned where needed.

## Phase 3: Protected-egress and fail-closed validation

Review the current trust model before modifying gateway-mode classification. Establish how
Snarkypuss can check that client forwarding uses provider-protected egress for each supported
transport while avoiding duplicate ownership of the provider's route and firewall policy.

Do not infer an interface name only from a protocol label. Where an actual interface cannot
be verified, represent it as unknown and keep the gateway state conservative. Examine route
and policy-routing observations, provider Kill Switch state, forwarding/NAT behavior, and
the management WireGuard exception. Define the required evidence for Protected VPN, Locked,
Direct VPS, and Unknown without equating a successful public-IP probe with proof of routing
safety.

### Phase 3 acceptance criteria

- Missing or contradictory evidence never reports Protected VPN.
- A provider disconnect or failed protocol transition cannot silently expose direct VPS egress.
- Private SSH, dashboard, and DNS management remain reachable in Locked mode.
- The code does not manipulate provider-created routes or tunnel interfaces directly.

## Phase 4: Provider adapter implementation

Extend the reviewed provider contract and implement NordVPN transport selection first.
Keep NordLynx working on supported 5.x and 6.x clients. Add only transports whose commands,
status fields, interface behavior, and safety characteristics have been verified on an
isolated test Linode.

Assess OpenVPN UDP, OpenVPN TCP, and NordWhisper individually. NordWhisper is an optional
obfuscating transport, not a mandatory replacement for NordLynx. Any changes to available
server groups or transport-specific connection targets must be modeled explicitly.

Extend Mullvad only after its actual supported transport capabilities have been established;
do not copy NordVPN's protocol names or behavior into the Mullvad adapter.

### Phase 4 acceptance criteria

- Each supported transport uses bounded, validated provider commands without a shell.
- Unsupported transports produce clear controlled errors.
- Switching transports cannot circumvent leak protection or corrupt saved target intent.
- NordLynx behavior remains compatible with the established baseline.

## Phase 5: Administrative API and dashboard

If protocol selection is needed in the UI, expose it through schema-validated, provider-neutral
control operations and authenticated administrative API endpoints. The interface should display
the selected transport separately from the observed transport and gateway protection state.

Present only options declared by the active adapter. Require deliberate confirmation for
changes that may interrupt gateway or management connectivity. Never silently change the
configured transport after a connection failure.

### Phase 5 acceptance criteria

- No provider-specific branching is required in the browser.
- Only reviewed operations cross the privileged control boundary.
- Status distinguishes configured intent, observed state, and unknown safety evidence.
- Existing destination editing and connection workflows remain usable.

## Phase 6: Automated regression tests

Add tests for capability declarations, validation, parsing, command selection, unsupported
protocols, failed transitions, unknown interfaces, and conservative gateway-mode results.
Cover control protocol, daemon, API, target persistence, and any dashboard model changes.

Include regression fixtures for NordVPN 5.x and the verified NordVPN 6.x output. Exercise
NordLynx, available OpenVPN variants, and NordWhisper separately, without inventing CLI
responses that have not been checked against the provider. Run the complete existing suite
and static checks before any deployment.

### Phase 6 acceptance criteria

- Existing tests and new transport-specific tests pass.
- No existing provider or destination selector regresses.
- Simulated provider failures cannot produce automatic Direct VPS mode.
- New behavior is covered in negative as well as success cases.

## Phase 7: Live integration and safety acceptance

Perform live tests only on an isolated Linode with independent LISH console recovery.
For each supported transport:

1. Verify provider connection, observed transport, interface, DNS, and public exit address.
2. Verify Windows WireGuard connectivity, private SSH, dashboard, and private DNS.
3. Verify that forwarded traffic follows the intended protected egress.
4. Disconnect the provider and confirm fail-closed forwarding while management stays reachable.
5. Repeat after protocol changes, provider reconnects, service restarts, and reboot.
6. Test malformed or unsupported protocol selections and interrupted transitions.
7. Record evidence and restore the known-good baseline after every test.

Do not treat unit tests, a successful provider status, or a public-IP lookup as a substitute
for these checks.

### Phase 7 acceptance criteria

- Every enabled transport has passed its own end-to-end and fail-closed tests.
- Management remains recoverable without exposing SSH or the dashboard publicly.
- Observed tunnel and routing behavior agrees with the status model.
- Production deployment has an explicit rollback and recovery procedure.

## Phase 8: Documentation and release preparation

Update provider guides, architecture, configuration, API documentation, user manual,
troubleshooting, release notes, and tests/README.md as applicable. Document supported
provider/client version combinations and transport limitations. Any architectural change
superseding an existing decision must be recorded in `development/DECISIONS.md`, preserving
the previous decision history.

Complete code review and test evidence before merging. Enable non-NordLynx transports in
production only after separate acceptance and an explicit release decision.

## Open questions

- Does NordVPN 6.x expose the actual protected interface for each transport consistently?
- How can SnarkyCtl independently validate egress protection without duplicating provider
  routing or firewall ownership?
- Should protocol policy be global per provider, or configurable for each stored destination?
- How do transport changes interact with NordVPN groups and explicit server selection?
- What is the correct and secure migration behavior for existing configurations?
- Which transports, if any, should the Mullvad adapter expose?
- Which observations survive reconnects and reboots, particularly for DNS and leak protection?

These questions must be answered through source review and real provider testing; this plan
does not preselect implementation answers.
