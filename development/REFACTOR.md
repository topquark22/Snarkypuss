# Provider-Neutral VPN Target Discovery Refactor

## Purpose

This document describes a planned refactor of SnarkyCtl's upstream-VPN target model and
editor so that VPN destinations can be **discovered dynamically through the active provider
adapter** rather than entered primarily as free-form text.

The immediate motivation is NordVPN. NordVPN can enumerate countries, cities, and specialty
groups, and can connect to a recommended server, a country, a city, a group, or a specific
server. The SnarkyCtl UI should use that information to present validated choices instead of
requiring an administrator to know provider-specific spelling and command syntax.

The design must remain provider-neutral. A future Mullvad adapter might discover countries,
cities, and relays. An OpenVPN-backed adapter might discover installed profiles instead of
geographic locations. The browser and HTTP API must not contain provider-specific branching.

This is a refactoring plan. The `vpn-target-discovery` branch starts from the same code
branchpoint as the documentation project and initially contains no implementation changes.

## Existing design

SnarkyCtl already has a provider abstraction in `VpnProvider`, an abstract base class. The
NordVPN implementation derives from this class and implements provider-specific status,
settings, connection, disconnection, leak-protection, selector validation, and target-schema
behavior.

The current target-editing design is already partly provider-neutral:

- `VpnProvider.target_schema()` returns reviewed data describing selector kinds.
- `ProviderTargetSchema` contains `SelectorKind` records.
- Each `SelectorKind` contains one or more `SelectorField` records.
- `SelectorFieldType` currently supports text, choice, boolean, and integer controls.
- `StoredTarget.selector` stores provider-owned structured selector data in SQLite.
- The generic dashboard requests the active provider's target schema and renders the editor.
- The browser does not construct or execute provider commands.

The missing piece is **dynamic option discovery**. A selector field can currently contain
static `choices`, but there is no provider-neutral way to express:

> The available values for this field must be queried from the active provider, and the
> query may depend on values already selected in other fields.

That limitation causes provider selections such as NordVPN country and city to be entered as
text even though the provider itself can enumerate valid choices.

## Design goals

The refactor should satisfy these goals:

1. Keep the browser provider-agnostic.
2. Keep the HTTP API provider-agnostic.
3. Keep provider command execution inside the privileged provider-adapter boundary.
4. Store the administrator's **selection intent**, not an accidentally resolved server.
5. Support dependent/cascading fields such as Country -> City.
6. Permit providers with no target discovery support.
7. Permit providers whose targets are not geographic.
8. Keep all provider-returned option data bounded and validated before exposing it to the
   browser.
9. Preserve the existing SQLite target catalogue and optimistic-concurrency model where
   possible.
10. Preserve backward compatibility with existing stored targets during migration.

## Non-goals

This refactor should not:

- make arbitrary provider CLI output directly available to the browser;
- allow the browser to submit arbitrary provider command arguments;
- turn SnarkyCtl into a generic shell-command front end;
- require every VPN provider to support discovery;
- assume that every provider uses Country/City/Server terminology;
- resolve a broad target such as a country into one fixed server at edit time;
- make provider discovery a public unauthenticated API;
- move provider ownership of routing, tunnel construction, or provider firewall policy into
  the web application.

## Core principle: store intent, resolve at connection time

A saved target should represent what the administrator asked for.

Examples:

```json
{"kind": "recommended"}
```

means:

> Let the provider choose its preferred server when a connection is made.

```json
{"kind": "country", "country": "united_states"}
```

means:

> Connect to the provider's preferred server in the United States each time this target is
> used.

```json
{
  "kind": "city",
  "country": "united_states",
  "city": "dallas"
}
```

means:

> Connect to the provider's preferred Dallas server each time this target is used.

Only a target such as:

```json
{"kind": "server", "server": "us715"}
```

means:

> Always request this exact provider server.

This distinction matters because provider load, topology, maintenance, and server inventory
change over time. Selecting "United States" or "Dallas" should remain a durable policy
choice rather than becoming a stale physical-server choice.

## Proposed provider polymorphism

Python supports conventional runtime polymorphism through abstract base classes and method
overriding. SnarkyCtl already uses this model in `VpnProvider`.

The provider interface should be extended with a new discovery operation. The exact type
names may change during implementation, but the conceptual contract should resemble:

```python
class VpnProvider(ABC):
    ...

    def target_schema(self) -> ProviderTargetSchema:
        ...

    def target_options(
        self,
        kind: str,
        field: str,
        context: JsonObject,
    ) -> TargetOptions:
        ...
```

The base implementation should return a controlled unsupported-operation error unless the
provider advertises dynamic discovery support.

Provider adapters then implement the method polymorphically.

For NordVPN:

```text
target_options(kind="country", field="country", context={})
    -> query NordVPN for countries

target_options(kind="city", field="country", context={})
    -> query NordVPN for countries

target_options(kind="city", field="city",
               context={"country": "united_states"})
    -> query NordVPN for cities in United States

target_options(kind="group", field="group", context={})
    -> query NordVPN for groups
```

A future Mullvad adapter could implement the same method using Mullvad-specific discovery.
An OpenVPN adapter could return installed profile names for a `profile` field.

No provider name should be tested in generic web or API code.

## Provider capabilities

`ProviderCapabilities` should gain an explicit capability describing target discovery, for
example:

```python
target_discovery: bool = False
```

This separates two concepts:

- **target selection**: the provider can connect to a structured configured target;
- **target discovery**: the provider can enumerate possible field values dynamically.

A provider may support target selection without discovery. In that case the generic editor
can continue to use text or static fields declared by the provider's target schema.

## Target schema extensions

`SelectorField` currently supports static `choices`. It should be extended so a provider can
state that a field obtains its choices dynamically.

One possible shape is:

```python
class SelectorOptionSource(StrEnum):
    STATIC = "static"
    PROVIDER = "provider"


class SelectorField(BaseModel):
    name: str
    label: str
    field_type: SelectorFieldType
    required: bool = True
    choices: tuple[str, ...] = ()
    option_source: SelectorOptionSource = SelectorOptionSource.STATIC
    depends_on: tuple[str, ...] = ()
```

The exact representation is less important than these semantics:

- static choice fields continue to work as they do now;
- provider-backed choice fields tell the dashboard to query the option API;
- `depends_on` identifies selector values needed before a query is meaningful;
- the dependency names must refer only to fields in the same selector kind;
- dependency cycles must be rejected when validating provider schemas.

For NordVPN, the City selector would conceptually be declared as:

```text
kind: city

country
    field_type: choice
    option_source: provider
    depends_on: []

city
    field_type: choice
    option_source: provider
    depends_on: [country]
```

This makes the dependency generic. The dashboard knows nothing about countries or cities; it
only knows that the second field cannot be populated until the first dependency has a value.

## Provider-neutral option model

Provider option responses should not be plain strings if a distinction between machine value
and display label may become useful.

A suitable provider-neutral model might be:

```python
class TargetOption(BaseModel):
    value: str
    label: str


class TargetOptions(BaseModel):
    provider: str
    kind: str
    field: str
    options: tuple[TargetOption, ...]
```

For NordVPN a machine value might be `united_states` while the display label is
`United States`.

This allows future providers to expose human-friendly labels without changing the value
stored in `StoredTarget.selector`.

The response should have strict limits on:

- option count;
- value length;
- label length;
- total provider output processed;
- provider-command execution time.

Provider option values must be treated as untrusted provider output and validated before
being returned through the control protocol or HTTP API.

## Control-daemon boundary

Dynamic discovery must follow the same security boundary as provider status and connection
operations.

The intended path is:

```text
Authenticated browser
        |
        v
SnarkyCtl HTTPS API
        |
        v
unprivileged ControlClient
        |
        v
/run/snarkyctl/control.sock
        |
        v
privileged control daemon
        |
        v
active VpnProvider implementation
        |
        v
provider CLI/API
```

The web process must not invoke `nordvpn`, Mullvad tools, OpenVPN commands, or provider APIs
directly.

The control protocol will require a new allowlisted request/response operation for target
option discovery. The request should contain only:

- provider identity expected by the active configuration;
- selector kind;
- field name;
- already-selected dependency values.

The daemon must validate all of those values against the provider's reviewed target schema
before dispatching discovery.

## HTTP API

The authenticated administrative API should expose a provider-neutral endpoint for option
queries.

The final URL is an implementation choice. A possible shape is:

```text
GET /api/v3/admin/vpn/target-options
    ?kind=city
    &field=country

GET /api/v3/admin/vpn/target-options
    ?kind=city
    &field=city
    &country=united_states
```

A POST endpoint with a small JSON request object may be preferable if dependency contexts
become more complex. The important requirement is that the API contract remain generic and
provider-neutral.

The API must authenticate the caller using the same administrative authentication used for
target-schema and target-catalogue editing.

Expected error cases should include stable codes for:

- discovery unsupported by the active provider;
- unknown selector kind;
- unknown field;
- missing dependency value;
- invalid dependency value;
- provider command failure;
- provider timeout;
- unparseable provider output;
- excessive provider output.

## Generic dashboard behavior

The target editor should remain entirely data-driven.

For each selector field:

1. Read the provider's target schema.
2. If the field is ordinary text, boolean, integer, or static choice, render it normally.
3. If the field is a provider-backed choice:
   - check whether all declared dependencies have values;
   - if not, disable the field and indicate which prior selection is required;
   - if so, query the target-options API;
   - populate the control using the returned labels/values.
4. When a dependency changes:
   - clear dependent field values;
   - invalidate any deeper dependent fields;
   - re-query options as needed.
5. Do not save a target until every required field has a currently valid value.

For NordVPN City selection, the user experience would therefore become:

```text
Destination type: [ Fastest in city v ]
Country:          [ United States v ]
City:             [ Dallas v ]
```

Selecting a different country automatically clears Dallas and reloads the city list.

The generic JavaScript must never contain logic such as:

```javascript
if (provider === "nordvpn") { ... }
```

Provider-specific behavior belongs in provider schema and adapter implementations.

## NordVPN implementation

The NordVPN adapter should initially support dynamic discovery for fields that the installed
NordVPN Linux CLI can enumerate reliably.

Expected operations are:

```text
nordvpn countries
nordvpn cities <country>
nordvpn groups
```

The adapter must:

- invoke the fixed NordVPN executable without a shell;
- use bounded execution time and bounded output;
- parse output conservatively;
- normalize values to forms accepted by `nordvpn connect`;
- return friendly labels separately from stored values where practical;
- reject malformed or unexpectedly large results.

### NordVPN selector kinds

The desired user-facing NordVPN destination types are:

| Selector | Meaning |
|---|---|
| Recommended | Fastest/recommended server selected by NordVPN |
| Country | Fastest/recommended server in one country |
| City | Fastest/recommended server in one city |
| Group | Server selected from one NordVPN specialty group |
| Server | One explicitly specified server |

The display labels in the UI should make broad selectors explicit, for example
**Fastest in country** and **Fastest in city**, so users do not mistake a country/city policy
for a pinned server.

### City connection correction

The existing NordVPN structured City selector stores both `country` and `city`, but the
current `connect_stored()` implementation passes only the city value to the NordVPN CLI.

As part of this refactor, the adapter should be reviewed against the installed/current
NordVPN syntax and changed to pass the complete validated city selector when required. This
should be covered by adapter unit tests.

## Exact NordVPN server discovery

The first increment should not depend on exact-server enumeration unless a stable and
supportable source is established.

NordVPN's Linux CLI documents country, city, and group discovery, while exact server names
can be accepted by `connect`. Exact-server enumeration may require NordVPN's server API
rather than the normal CLI.

Therefore implementation should be staged:

### Increment 1

Implement dynamic discovery for:

- countries;
- cities dependent on country;
- groups.

Keep exact Server as a validated advanced text field if necessary.

### Increment 2

Evaluate provider-side exact-server discovery. If the NordVPN server API is used:

- HTTP access must occur within the trusted provider adapter/control boundary, not in browser
  JavaScript;
- HTTPS and certificate verification are mandatory;
- response size and timeout must be bounded;
- API response schemas must be validated;
- server results may optionally be filtered by country/city before being returned to the
  editor;
- the feature must fail safely if NordVPN changes or removes the endpoint.

The general target-discovery architecture must not depend on Increment 2.

## Future providers

The abstraction must be useful without geographic assumptions.

### Mullvad example

A future Mullvad provider might expose:

```text
Country -> City -> Relay
```

or another hierarchy supported by its installed client/API.

The generic dashboard would render that hierarchy using the same `depends_on` mechanism.

### OpenVPN example

OpenVPN is a protocol/client rather than a commercial provider. An OpenVPN adapter might
instead expose:

```text
Profile
    option_source: provider
```

where discovery enumerates administrator-approved `.ovpn` profiles from a protected local
directory.

No changes to the generic target editor should be required.

## Caching and freshness

Provider discovery data changes more slowly than connection status but is not immutable.

Initial implementation may perform discovery on demand without persistent caching. If
latency becomes noticeable, short-lived in-memory caching can be added later.

Any cache should be:

- provider-scoped;
- query/context-scoped;
- bounded in entry count;
- short-lived;
- invalidated on provider change or daemon restart;
- treated only as UI assistance, never as the authoritative validation of a stored target.

A selector must still be validated again by the provider adapter when the catalogue is
saved and when a connection is attempted.

## Stored-target validation

Dynamic discovery improves editing but does not replace server-side validation.

The provider adapter remains authoritative for `validate_selector()`.

When saving a catalogue:

- selector shape must match the provider schema;
- values must satisfy provider validation rules;
- malformed or unknown fields must be rejected.

A discovered value may later disappear from the provider. Existing stored targets should not
be deleted automatically. On connection, the provider should return a controlled error if the
target is no longer valid or available.

The editor may warn when a previously stored value no longer appears in current discovery
results, but it must not silently substitute a different stored selector.

## Backward compatibility

Existing SQLite catalogue rows must remain readable.

The current NordVPN selector documents already distinguish kinds such as recommended,
country, city, group, server, and legacy. Dynamic discovery should enhance editing without
requiring a destructive data migration.

Legacy selectors should continue to function through the existing migration/compatibility
path until they are explicitly converted by an administrator or a separately reviewed
migration.

The target schema/API may need a version bump if the serialized schema changes incompatibly.
Any version change should be explicit and covered by API/control-protocol compatibility tests.

## Security considerations

Dynamic discovery increases the amount of provider output accepted by SnarkyCtl. The
following controls are required:

- fixed trusted provider executable or reviewed provider API endpoint;
- no shell execution;
- allowlisted provider operations only;
- strict timeouts;
- strict output-size limits;
- strict option-count and field-length limits;
- schema validation of provider responses;
- authenticated administrative HTTP access;
- control-daemon validation before provider dispatch;
- no arbitrary command fragments supplied by the browser;
- HTML rendering through ordinary escaped text, never provider-supplied markup.

Discovery is read-only with respect to provider connection state. Querying options must not
connect, disconnect, change routes, change leak protection, or modify the provider's
configuration.

## Testing plan

The refactor should be developed with tests at each layer.

### Model tests

Verify:

- provider-backed option fields serialize/validate correctly;
- dependencies reference valid fields;
- duplicate/cyclic dependencies are rejected;
- option values and labels are bounded.

### Base-provider tests

Verify:

- providers default to discovery unsupported;
- unsupported discovery returns a controlled provider error;
- capability flags accurately reflect support.

### NordVPN adapter tests

Use fake command runners to verify:

- countries are parsed and normalized;
- cities require country context;
- groups are parsed and normalized;
- malformed provider output is rejected;
- command failures and timeouts become stable `ProviderError` codes;
- exact expected argument arrays are used;
- city connections use the complete validated selector;
- discovery commands never mutate provider state.

### Control protocol tests

Verify:

- discovery requests are schema-validated;
- only active/allowed providers can be queried;
- unknown kinds/fields are rejected before command execution;
- dependency context is validated;
- bounded provider options are returned correctly.

### API tests

Verify:

- authentication is required;
- provider-neutral option responses are returned;
- controlled daemon/provider errors map to stable API errors;
- no raw provider stderr leaks to the browser.

### Dashboard tests

Verify:

- provider-backed fields load dynamically;
- dependent fields remain disabled until prerequisites are selected;
- changing a dependency clears stale child values;
- loading/error states are visible;
- catalogue save uses stored machine values rather than display labels;
- no provider-specific conditional logic appears in generic JavaScript.

## Suggested implementation sequence

A safe sequence is:

1. Extend provider-neutral models for dynamic field discovery.
2. Extend `VpnProvider` with default unsupported discovery behavior.
3. Extend the control protocol with a read-only target-options operation.
4. Extend the authenticated administrative API.
5. Implement NordVPN country/city/group discovery.
6. Correct NordVPN city connection argument handling.
7. Update the generic dashboard to render cascading provider-backed choice fields.
8. Add end-to-end tests for target editing and catalogue persistence.
9. Evaluate exact NordVPN server discovery separately.
10. Update provider/user documentation only after the implementation behavior is accepted.

Each increment should leave existing configured targets and ordinary connect/disconnect
behavior functional.

## Acceptance criteria

The refactor is complete when all of the following are true:

- `VpnProvider` exposes a provider-neutral discovery interface.
- Providers can explicitly advertise whether they support dynamic target discovery.
- Target schemas can declare provider-backed and dependent option fields.
- The control daemon can retrieve options without exposing arbitrary provider commands.
- The authenticated API exposes the same provider-neutral operation.
- The generic dashboard can render at least one cascading selector without provider-specific
  JavaScript.
- NordVPN Country, City, and Group selectors are populated from live provider discovery.
- Changing a country refreshes/clears the dependent city field correctly.
- Stored targets preserve broad intent rather than pinning to an arbitrary resolved server.
- Existing target catalogues remain compatible.
- NordVPN city connection behavior uses the validated full selector correctly.
- Unsupported providers continue to function without implementing discovery.
- Provider discovery failures cannot alter connection state or bypass normal security
  boundaries.
- Automated tests cover model, adapter, control, API, and UI behavior.

## Architectural result

After this refactor, SnarkyCtl will have a clean three-part provider contract for target
management:

```text
target_schema()
    Describe what kinds of target this provider can represent.

target_options(kind, field, context)
    Discover currently available values for a provider-backed field.

connect_stored(target)
    Execute a connection using the saved, validated user intent.
```

This keeps the dashboard generic while allowing each provider adapter to implement its own
selection vocabulary and discovery mechanism. It also creates a reusable foundation for
future VPN integrations without baking NordVPN assumptions into SnarkyCtl's UI or API.
