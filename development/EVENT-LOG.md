# SnarkyCtl Event Log and Notifications — Design

## 1. Purpose and sequencing

Provide an operator-visible account of significant SnarkyCtl activity without creating a
record of the user's network identity or traffic. The event framework is a general
SnarkyCtl capability, not part of the automatic VPN recovery implementation.

Implement and review this design on `feature/event-log`, branched from `main`.
Merge and validate the event framework before rebasing `feature/auto-recovery` onto
the updated `main`. The recovery feature will subsequently publish events through
the shared framework; it must not supply its own log store or special dashboard API.

This document is a proposed specification. No event logging, API, retention, deletion,
or dashboard behavior described here is implemented merely by adding this document.

## 2. Goals

- Notify an authenticated operator about significant gateway and control events.
- Provide a small, comprehensible event history in the existing SnarkyCtl console.
- Support structured, provider-neutral events emitted by trusted application code.
- Make persistence an explicit opt-in rather than an incidental consequence of logging.
- Provide a **Delete all log history** button that clears every event-history record
  managed by SnarkyCtl, including event-derived notifications.
- Preserve the private management plane and least-privilege control-daemon boundary.
- Make retention, deletion semantics, and the limits of SnarkyCtl's control explicit.

## 3. Privacy invariants

### 3.1 Record operations, not network activity

An event describes what SnarkyCtl did or observed about the gateway, not what an
individual did through the gateway. The event framework must never collect or retain:

- The user's apparent public IP, VPS public IP, upstream VPN exit IP, or WireGuard peer IP.
- Other source or destination IP addresses, ports, or per-flow connection records.
- DNS queries, browsing history, URLs visited by VPN users, or packet contents.
- Authentication secrets, API tokens, recovery keys, private keys, or passwords.
- Raw provider commands, stdout/stderr, exception messages, or unvalidated text that
  could contain the above.
- Hostnames or server identifiers inferred from network activity.

Do not create hidden fields for these values, log them and redact them later, or
send them to the browser in fields that are not displayed. The producer must construct
an event exclusively from approved typed fields. Never serialize arbitrary error
objects, provider `details`, subprocess results, request bodies, or full status models.

Destination aliases, display names, cities, countries, exact provider servers,
endpoint URLs, usernames, process identifiers, and raw command diagnostics are
**excluded from the default event schema**. The operator may see such information
in an ordinary live status view; that does not authorize recording it in history.

An optional future extension that stores additional contextual fields requires a
separate privacy review and explicit opt-in. A generic `message` or `metadata`
dictionary must not become an escape hatch around this rule.

### 3.2 Distinguish event history from other logs

SnarkyCtl event history is separate from system-level diagnostics. The existing
systemd journal, NordVPN/WireGuard logs, VPS provider logs, Uvicorn access logs,
backups, snapshots, or third-party services can have independent retention and
may contain network identifiers. SnarkyCtl cannot promise to delete those records.

The design must audit existing SnarkyCtl diagnostic logging, including the control
daemon's request/peer logging and Uvicorn's access logging, for sensitive output.
Avoid writing structured event payloads into journald by default; otherwise the
Delete all history control would give a misleading impression of erasure.
Essential service diagnostics may remain in journald, with sanitized messages.
No new logging of client addresses or event details should be introduced there.

Do not treat journald as the event-history repository. In particular, do not grant
the unprivileged web service journal-reading privileges.

### 3.3 No telemetry or external notification service

Events remain on the VPS and are requested solely over the authenticated private
management connection. Do not add analytics, telemetry, email, webhooks, mobile push,
remote logging, or a browser third-party dependency as part of this feature.

## 4. Event schema and producers

Use a versioned, strict, provider-neutral model owned by the privileged control
daemon. Illustrative shape (not a finalized wire encoding):

```json
{
  "schema_version": 1,
  "id": "opaque-event-id",
  "occurred_at": "2026-11-05T20:45:18Z",
  "severity": "info",
  "code": "VPN_CONNECTED",
  "result": "success"
}
```

Required fields:

| Field | Constraint |
|---|---|
| `schema_version` | Exact supported schema version; reject unknown versions |
| `id` | Opaque, unguessable event identifier; no network identifier embedded |
| `occurred_at` | Server-generated UTC timestamp; display in the browser's local time |
| `severity` | Fixed enum: `info`, `warning`, `error` |
| `code` | Fixed enum from a compiled allowlist |
| `result` | Fixed enum when applicable, not free-form diagnostic text |

Only explicitly enumerated, non-identifying values such as a failure count or safe
diagnostic **code** may be added with a schema change. Render localized/display
strings by mapping trusted codes to reviewed text; do not persist arbitrary strings.

Initial general-purpose event codes:

| Code | When emitted |
|---|---|
| `VPN_CONNECTED` | Operator-requested connection completed |
| `VPN_CONNECT_FAILED` | Operator-requested connection failed |
| `GATEWAY_MODE_CHANGED` | Operator changed VPN/LOCKED/DIRECT mode |
| `GATEWAY_MODE_CHANGE_FAILED` | Requested mode change failed |
| `CONTROL_OPERATION_REJECTED` | Significant safety rejection, not every invalid request |

Later, on `feature/auto-recovery`, add:

| Code | When emitted |
|---|---|
| `UPSTREAM_UNREACHABLE` | The configured failure threshold was reached |
| `RECOVERY_STARTED` | Automatic protected recovery was initiated |
| `RECOVERY_SUCCEEDED` | VPN was reconnected **and** upstream connectivity verified |
| `RECOVERY_FAILED` | Recovery did not restore verified connectivity |
| `RECOVERY_SKIPPED` | Recovery could not safely proceed; reason is a safe code |

Do not generate events for every status poll, packet, DNS request, or heartbeat.
Bound and coalesce repetitive failures so an unstable upstream cannot flood history.
Emit one result per attempted operation, avoiding duplicate events during retries.

The shared framework must be usable even when automatic recovery is disabled.

## 5. Retention modes

Event history is independently configurable; changing VPN target selection or mode
does not alter these settings. Use the root-owned SnarkyCtl configuration, not browser
local storage, to define the authoritative retention policy.

| Mode | Behavior |
|---|---|
| `off` | No event history retained; live status and current safety warnings still work |
| `memory` (default) | Bounded ring buffer in the privileged daemon; no history file; lost when daemon exits |
| `persistent` (opt-in) | Bounded dedicated SnarkyCtl-owned history store on disk; survives daemon restart |

Proposed initial defaults, subject to implementation review:

- `memory`: maximum 100 records, with a maximum age of 24 hours while the daemon is
  running; evict the oldest events first. A browser refresh does not clear the buffer.
- `persistent`: require explicit administrator configuration, maximum-age and
  maximum-record limits, and a dedicated root-owned path. Do not silently migrate
  any existing journal entries or historical logs into it.
- `off`: neither event buffer nor persistent event-history storage may be populated.

The configuration model must reject unknown options and invalid combinations.
Avoid creating an empty persistent file or directory in `off` or `memory` mode.
The existing SQLite VPN target catalogue remains separate: it is **not** an event
database, and the selected target must not be copied into event-history storage.

If the mode changes from `persistent` to `memory` or `off`, disclose and require a
deliberate decision about deleting pre-existing persistent event history; simply
switching off recording must not misleadingly imply old files were erased.

## 6. Storage architecture and trust boundaries

The privileged control daemon owns the event producer, retention policy, event
buffer, and any opt-in persistent store. The unprivileged FastAPI/Uvicorn process
is an authenticated presentation/API proxy and has **no direct filesystem access**
to event storage or systemd journal data.

Use the existing authenticated Unix control socket and versioned request/response
protocol for bounded, read-only event retrieval and explicit deletion commands.
The daemon continues verifying peer credentials; the HTTPS service stays bound to
the private WireGuard management address.

For persistent mode, constrain storage to a dedicated root-owned file/directory
under the package's approved state directory, with restrictive permissions and
explicit size/rotation/retention bounds. Avoid symlink traversal, arbitrary paths,
SQL supplied by the browser, file-name inputs, or shell invocation. No uncontrolled
backup, archive, or rotating copy should be created by SnarkyCtl.

An event failure must not make the VPN less safe or prevent a user from requesting
LOCKED mode. If the log subsystem is unavailable, report it as an independent
status failure; do not fabricate an empty history or a successful deletion.

## 7. Console presentation

### 7.1 Notification beneath gateway mode

Show a compact, accessible notification beneath the gateway-mode panel when a
significant new event is observed. Include a short description, the event's local
timestamp, and a link to the corresponding history entry when available.

- `info`: successful operation or recovered incident.
- `warning`: degraded connectivity, skipped recovery, or operation requiring attention.
- `error`: failed recovery or significant control-operation failure.
- While recovery is in progress, show a temporary state indicator derived from
  current state; do not mislabel a reconnect as a verified recovery.

A successful recovery notification may remain visible for up to 24 hours **only
while its event remains in the configured history**. No event persistence is
introduced solely to keep a notification visible. After daemon restart under
`memory` mode, prior event notifications disappear.

The existing public-IP exposure warning and unknown gateway safety indication
always take precedence over informational event notifications. Clearing history
must never suppress a current unsafe-mode warning.

### 7.2 Event history viewer

Place a collapsible **Event Log** section near the bottom of the dashboard,
before Advanced Gateway Modes. Present newest first, with timestamp, severity,
human-readable description, and a small detail view of allowlisted fields.

- Load the latest 25 events initially; permit bounded pagination of older events.
- Provide Refresh and a clear indication of the active history mode.
- Continue the existing dashboard's authenticated, five-second status refresh;
  event history may be fetched on demand or efficiently checked for newer events.
- Render with text nodes, not untrusted HTML; preserve keyboard and screen-reader access.
- Differentiate `No recorded events`, `History disabled`, and `History unavailable`.
- Do not store events in browser `localStorage`, `sessionStorage`, IndexedDB,
  service-worker caches, or analytics; use in-memory UI state only.
- Apply `Cache-Control: no-store` to event-related HTTP responses.

The viewer is an operational event feed, **not** an unrestricted server log reader
or a console for arbitrary journal searches.

## 8. HTTP and control API (proposed)

Use existing API conventions, authentication, versioning, error envelopes,
request size limits, and same-origin protections documented in `docs/10_API.md`.
Illustrative routes:

| Route | Purpose |
|---|---|
| `GET /api/v2/events` | Retrieve a bounded, newest-first page of sanitized events |
| `GET /api/v2/events/status` | Retrieve retention mode, availability, and limited counts |
| `POST /api/v2/events/clear` | Delete **all** SnarkyCtl-managed event history |

The list operation supports bounded `limit` and opaque cursor parameters; it
never accepts filesystem paths, provider commands, or arbitrary queries.
Use existing HTTP Basic authentication and the private management interface.
For `POST`, enforce the existing JSON content type, `X-SnarkyCtl-Request: 1`,
Origin and Fetch Metadata restrictions before calling the daemon.
Require an explicit confirmation token/body validated at both API and control
protocol boundaries. Clear is administrative even though it cannot alter VPN mode.

The response must distinguish success from a partial or failed clear operation.
Do not return deleted event bodies in the response.

## 9. Delete all log history

### 9.1 UI interaction

Add a clearly labeled **Delete all log history** button within the Event Log
section, with an explicit confirmation dialog explaining the effect and limits.
Do not trigger deletion merely by expanding the section or pressing Refresh.

The confirmation copy must say, in substance:

> This permanently clears event history maintained by SnarkyCtl, including any
> in-memory records, optional on-disk history, and notifications derived from
> those events. It does not delete Linux system journals, Uvicorn or provider
> logs, VPS provider records, external backups, or other independent logs.

Disable repeated submissions while the action is in flight. On success, clear
the event list and any event-derived banners immediately, and show a short
non-persisted success acknowledgement. Do not write a new `HISTORY_CLEARED`
event into the just-cleared history.

### 9.2 Deletion contract

A successful clear must:

1. Erase the current daemon's entire in-memory event ring, regardless of
   configured retention mode.
2. Delete all persistent event-history records, archives, and rotated copies
   **managed by SnarkyCtl**, if any exist; include history from a previously
   selected retention mode.
3. Invalidate pending buffered writes and in-flight event publication from before
   the clear barrier (e.g., with a generation/epoch guard), so cleared events
   cannot be resurrected by a late write or concurrent worker.
4. Invalidate cached event pages/derived banners for connected browsers on their
   next refresh and make stale pagination cursors unusable.
5. Preserve current connectivity status, mode, target catalogue, safety warnings,
   authentication, and other non-history application state.
6. Return success only after the daemon has confirmed the deletion under its
   control. If deletion fails or is incomplete, report an error without asserting
   that history has been removed.

The clear operation applies across **all** SnarkyCtl-managed history stores; it
must work even if persistent recording is currently switched off but an old
SnarkyCtl history file remains. The UI must not misleadingly suggest that
changing the retention mode alone has deleted prior records.

Events that occur genuinely **after** the clear barrier may appear as new events.
A clear does not disable future collection; choose `off` separately to do that.
No event-derived notification from before the barrier may reappear.

Filesystem deletion is a logical deletion under SnarkyCtl's control, not a
guarantee of forensic secure erasure from SSD wear-leveling, snapshots, backup
systems, or underlying host storage. Document this limit prominently rather
than promising irreversible physical destruction.

### 9.3 Out-of-scope records

The button must not try to erase or truncate `journalctl` history, Uvicorn
access/error logs, NordVPN logs, WireGuard/systemd diagnostics, OS audit records,
cloud-provider records, or third-party backups. These are not SnarkyCtl-managed
event history and require separate administrative controls.

The request to clear history may itself be observable in ordinary system-level
service logs under existing logging behavior; do not claim otherwise. Avoid
including history contents or sensitive identifiers in such diagnostics.

## 10. Operational safety and failure handling

- Event recording is never a precondition for VPN connect/disconnect or LOCKED mode.
- Event API reads and deletion cannot invoke VPN mode changes.
- Bounded memory, disk, query size, and result count must prevent log-volume DoS.
- Serialized deletion must be safe against event producer concurrency.
- History unavailability is shown distinctly from an empty event list.
- A failed recovery must not be reported as a successful recovery just because
  the provider reports `CONNECTED`; verify upstream access separately.
- Timestamp ordering and cursor behavior must be deterministic across refresh,
  retention eviction, restart, and clear.
- Privacy mode `off` must not silently persist incident history in another store.
- Do not introduce privileged journal access, a new public listener, or a network
  dependency for event storage or display.

## 11. Verification and acceptance criteria

### Privacy and data minimization

- Tests reject prohibited IP fields, URLs, free-form exception text, and arbitrary
  provider metadata at every event producer and serializer boundary.
- Inspect emitted events, daemon diagnostics, HTTP responses, browser state,
  and optional persistent storage for forbidden data.
- Verify memory/off modes never create event-history files.
- Audit Uvicorn/control-daemon diagnostic logging separately; explicitly document
  records remaining outside the history feature's control.

### Functional behavior

- A manual VPN mode change and a failed connection each generate one expected,
  sanitized event; routine status polling generates none.
- Notifications reflect severity and do not obscure current exposure warnings.
- Event history survives browser refresh and is bounded, ordered, and paginated.
- Memory history expires after daemon restart; persistent history survives restart
  only when expressly enabled.
- `off` exposes live status without retaining event history.
- Events are unavailable to unauthenticated clients and are never exposed on
  the VPS public interface.

### Delete all history

- Confirmation is mandatory; the same-origin mutation requirements are enforced.
- Clear removes all memory and opt-in persistent history managed by SnarkyCtl,
  including legacy files from a prior retention mode and managed rotated copies.
- A browser refresh, second browser session, pagination request, and daemon
  restart do not restore events erased before the clear barrier.
- Simulate concurrent event publication and queued disk writes; old events cannot
  reappear after successful deletion.
- Current safety warnings remain visible; new events after deletion work normally.
- Simulated filesystem deletion failure yields an explicit error and no false
  success indication.
- Test that unrelated systemd journals and Uvicorn/provider logs are untouched.

## 12. Development increments

1. Define a strict, versioned event schema and approved event codes; write
   data-minimization and serialization tests first.
2. Implement bounded daemon-owned in-memory history with `off` and `memory`
   policies, including concurrency and eviction tests.
3. Extend the Unix control protocol and authenticated HTTP API for read/status/
   clear; implement confirmed deletion and stale-cursor invalidation.
4. Add the console Event Log viewer, notifications, and Delete all history dialog.
5. Add the separately opted-in persistent store with bounded retention and
   complete managed-store deletion; verify restart and migration behavior.
6. Audit system-level diagnostic boundaries, update operator/API/configuration
   documentation, package tests, and perform UAT on `snarkypuss-test`.
7. Once merged to `main`, rebase `feature/auto-recovery` and replace ad-hoc
   recovery log messages with the approved event codes and notifications.

**Out of scope:** Implementing automatic recovery itself, redesigning the VPN
provider interfaces, general-purpose journal viewing, external notifications,
retention of client traffic, and changes to VPN-target persistence.
