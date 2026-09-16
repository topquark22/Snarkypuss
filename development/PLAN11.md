# VPN Target Discovery Project Plan

## Purpose

This plan ("Plan 11") turns the provider-neutral target-discovery design in `REFACTOR.md` into an
implementation sequence for the `vpn-target-discovery` branch.

The first delivery target is NordVPN discovery for countries, cities, and groups while
keeping the control protocol, HTTP API, target editor, and stored-target model provider
neutral.

Exact NordVPN server discovery is not part of this increment.

## Principles

The implementation must preserve these constraints throughout the project:

- provider-specific discovery remains inside the privileged provider adapter;
- the browser and HTTP API contain no NordVPN-specific branching;
- stored targets continue to represent selection intent rather than a resolved server;
- existing SQLite catalogue rows remain readable without a destructive migration;
- provider output is treated as untrusted and is bounded and validated before exposure;
- dynamic discovery assists editing but does not replace authoritative selector validation;
- existing providers that do not support discovery continue to work unchanged.

## Phase 1: Discovery model and provider interface

Extend the provider-neutral target model before adding any NordVPN-specific behavior.

1. Add an explicit target-discovery capability to `ProviderCapabilities`.
2. Extend `SelectorField` so choice fields can identify their option source as static or
   provider-backed.
3. Add field dependency metadata for cascading choices such as Country -> City.
4. Add provider-neutral target option and target option response models with separate stored
   values and display labels.
5. Validate provider target schemas so dependencies refer to fields in the same selector kind
   and dependency cycles are rejected.
6. Extend `VpnProvider` with the target-option discovery operation and a controlled default
   behavior for providers that do not support discovery.

### Phase 1 acceptance criteria

- Existing static target schemas continue to validate and render as before.
- A provider can declare a dynamic choice field without generic code knowing its semantics.
- Invalid dependencies and cycles are rejected during schema validation.
- Providers without discovery support return a controlled unsupported result.

## Phase 2: Control protocol and daemon dispatch

Add discovery to the existing privileged control boundary.

1. Define an allowlisted control request for target option discovery.
2. Define the corresponding provider-neutral response and stable error representation.
3. Extend `ControlClient` with a discovery operation.
4. Extend the privileged daemon dispatcher to handle the request.
5. Validate selector kind, field name, provider identity, and dependency context against the
   active provider's reviewed target schema before invoking the adapter.
6. Reject undeclared context fields and missing or malformed dependency values.

### Phase 2 acceptance criteria

- The unprivileged web process cannot invoke provider commands directly.
- Only schema-declared discovery requests reach the provider adapter.
- Unsupported discovery, invalid requests, and provider failures produce controlled errors.
- Existing control protocol operations remain compatible.

## Phase 3: NordVPN discovery adapter

Implement the first provider-specific discovery backend.

1. Add bounded execution support for the fixed NordVPN executable without using a shell.
2. Implement country discovery using `nordvpn countries`.
3. Implement city discovery using `nordvpn cities <country>`.
4. Implement group discovery using `nordvpn groups`.
5. Parse output conservatively and normalize values into forms accepted by NordVPN connect
   operations.
6. Produce friendly display labels separately from stored machine values where practical.
7. Enforce limits on execution time, provider output size, option count, option value length,
   and option label length.
8. Reject malformed, excessive, or unparseable output rather than passing it upward.
9. Update the NordVPN target schema so Country, City, and Group use provider-backed choices;
   City declares Country as a dependency.
10. Keep exact Server as the existing validated advanced text field.

### Phase 3 acceptance criteria

- NordVPN countries, cities, and groups can be enumerated through `VpnProvider` without
  provider-specific knowledge in the caller.
- City discovery cannot run without a valid country context.
- Malformed or excessive CLI output fails safely.
- Recommended and Server selectors continue to behave correctly.

## Phase 4: NordVPN connection review

Review connection behavior while the NordVPN selector model is already under test.

1. Verify the current installed NordVPN CLI syntax for connecting to a city.
2. Review `connect_stored()` for all structured selector kinds.
3. Correct City connection handling so the complete validated city selector is supplied when
   required by the current CLI.
4. Add regression tests for Recommended, Country, City, Group, Server, and legacy selectors.

### Phase 4 acceptance criteria

- Every structured NordVPN selector produces the intended CLI invocation.
- A City target preserves both country and city intent and connects correctly.
- No broad selector is silently converted into a pinned server.

## Phase 5: Authenticated HTTP API

Expose discovery through a generic administrative endpoint.

1. Add a provider-neutral target-options request to the authenticated administrative API.
2. Pass only selector kind, field, and declared dependency context to `ControlClient`.
3. Map control/provider failures to stable API errors.
4. Bound request data and reject unknown context parameters.
5. Keep the API contract independent of NordVPN terminology.

### Phase 5 acceptance criteria

- An authenticated caller can request options for any schema-declared provider-backed field.
- The endpoint contains no provider-name branching.
- Invalid kind, field, dependency, timeout, parse failure, and unsupported discovery cases are
  distinguishable and controlled.
- Existing administrative authentication requirements apply unchanged.

## Phase 6: Generic cascading target editor

Teach the dashboard to render and maintain provider-backed choices from schema metadata.

1. Render provider-backed choice fields using the same generic field-rendering path as other
   selector fields.
2. Disable a field until all declared dependencies have values.
3. Query the target-options API when a provider-backed field becomes eligible.
4. Populate controls using returned option labels and values.
5. When a dependency changes, clear its dependent values and recursively invalidate deeper
   dependencies.
6. Re-query newly eligible fields as needed.
7. Prevent saving while a required field is missing, loading, invalid, or stale relative to a
   changed dependency.
8. Handle a stored value that no longer appears in current discovery results without silently
   replacing it.
9. Update NordVPN selector labels so broad choices are explicit, including `Fastest in
   country` and `Fastest in city`.

### Phase 6 acceptance criteria

- Country -> City cascading works without NordVPN-specific JavaScript.
- Group choices populate dynamically.
- Changing Country clears and reloads City.
- Existing static, text, boolean, and integer fields still render correctly.
- A disappearing provider option is surfaced to the administrator rather than silently
  substituted.

## Phase 7: Validation and regression testing

Complete the increment with tests across each architectural boundary.

1. Add model tests for option sources, dependencies, and dependency-cycle rejection.
2. Add provider base-class tests for unsupported discovery.
3. Add NordVPN parser and command-construction tests using controlled command output.
4. Add control protocol and daemon-dispatch tests for valid and invalid discovery requests.
5. Add API tests for authentication, successful discovery, and stable error cases.
6. Add dashboard tests for dependent-field loading, clearing, and stale-value handling where
   the existing test infrastructure permits.
7. Run the complete existing test suite to catch regressions outside target discovery.
8. Perform a manual integration test on the VPS against the installed NordVPN client.

### Phase 7 acceptance criteria

- Automated tests cover normal discovery and failure paths.
- Existing stored target fixtures continue to load without migration.
- Existing non-discovery provider behavior is unchanged.
- Live NordVPN discovery returns usable Country, City, and Group choices.
- A target selected through the UI can be saved, reloaded, and connected successfully.

## Phase 8: Documentation and release preparation

Update documentation only after the implementation behavior is settled.

1. Update architecture documentation for the discovery path and trust boundary.
2. Update NordVPN documentation with the dynamically discovered target types.
3. Document the generic provider discovery contract for future adapters.
4. Record any implementation decisions that differ materially from `REFACTOR.md`.
5. Update version and release notes when the branch is ready for release, without creating or
   pushing release tags unless explicitly requested.

## Deferred work

The following work is intentionally outside this project increment:

- exact NordVPN server enumeration through NordVPN's server API;
- persistent discovery caching;
- Mullvad target discovery;
- OpenVPN profile discovery;
- automatic rewriting or deletion of stored targets whose discovered values disappear;
- any provider-specific behavior in the browser or generic HTTP API.

These can be added later without changing the provider-neutral discovery architecture.

## Implementation order

The phases should normally be implemented in order because each establishes the contract used
by the next layer:

```text
Models and provider interface
        |
        v
Control protocol and daemon
        |
        v
NordVPN discovery adapter
        |
        v
NordVPN connection review
        |
        v
Authenticated HTTP API
        |
        v
Generic target editor
        |
        v
Integration and regression testing
        |
        v
Documentation and release preparation
```

Each phase should be kept independently reviewable. Changes should remain narrowly scoped to
that phase, with tests added alongside the behavior they cover rather than deferred until the
end.
