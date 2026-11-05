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
- Keep all SnarkyCtl event history exclusively in bounded process memory, never on disk.
- Provide a **Delete all log history** button that clears every event-history record
  managed by SnarkyCtl, including event-derived notifications.
- Preserve the private management plane and least-privilege control-daemon boundary.
- Make restart loss, deletion semantics, and the limits of SnarkyCtl's control explicit.

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

Events remain in volatile SnarkyCtl web-process memory and are requested solely over the
authenticated private management connection. Do not add analytics, telemetry, email,
webhooks, mobile push, remote logging, or a browser third-party dependency.

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

## 5. Volatile retention policy

**No SnarkyCtl event history is ever persisted to disk.** This includes connection
failures, unexpected disconnections, automatic recovery, and other operational events.
Do not offer a persistent-retention mode, write an event-history file or database, or
copy event history into the target SQLite database or system journal.

Use root-owned SnarkyCtl configuration to select the policy; do not store a policy in
the browser. The only permitted modes are:

| Mode | Behavior |
|---|---|
| `off` | No event history is retained; live status and current safety warnings continue |
| `memory` (default) | A bounded ring buffer in the SnarkyCtl **web application process** |

In `memory` mode, retain at most 100 events for at most 24 hours; evict the oldest
events first. Browser refreshes and new authenticated browser sessions can retrieve
events while the web application process is alive. **Restarting the SnarkyCtl web
service (Uvicorn) clears all recorded events and their derived notifications.**
There is no restart recovery, disk backup, export file, or replay from system logs.
A daemon-only restart does not itself erase the web process's current buffer, though
events may be missed while the producer is unavailable.

This deliberate tradeoff favors privacy over long-term auditability. Events produced
while the web service is stopped or unable to receive them are lost, rather than
stored for later delivery. It is acceptable for a historical disconnection to be
unavailable after a web restart; current connection and exposure status must still
be collected independently when the console reconnects.

The configuration must reject unknown policy modes. No SnarkyCtl event-history
files, databases, archives, backups, or persistent log queues may be created in
either mode. The existing SQLite VPN target catalogue is unrelated and unchanged:
event history does not persist the selected VPN target.

## 6. Volatile event transport and trust boundaries

The privileged control daemon emits only strictly typed, approved event records.
The unprivileged FastAPI/Uvicorn web service owns the bounded in-memory event
buffer, retention policy enforcement, authenticated event APIs, and event-derived
notifications. It must not gain privileges, read systemd journals, or access
provider logs to reconstruct history.

Provide a local, non-persistent Unix-domain IPC path for event delivery from the
privileged daemon to the web process; use fixed root-controlled endpoints,
restrictive socket permissions, and verified peer credentials. Choose and test the
exact socket and message framing during implementation. Do not expose an event
receiver on TCP/UDP, accept arbitrary browser-supplied event records, or allow the
event channel to execute provider commands.

Event delivery must be bounded and best-effort: failure or absence of the web
consumer must not delay, fail, or roll back a VPN operation. No daemon-side backlog,
disk spool, or retained replay stream is permitted. An event may be dropped while
the web process is offline, and must not reappear after the web process restarts.
Use a single authoritative in-memory event buffer per running web instance;
if multi-worker hosting is introduced later, it needs an explicitly reviewed
volatile sharing design rather than silently creating inconsistent histories.

The HTTPS console stays on the private WireGuard management address, using its
existing authentication and same-origin controls. Event transport and clearing
do not alter VPN mode, routing, firewall, or the daemon's control privileges.

An event subsystem failure must not make VPN operation less safe or prevent
LOCKED mode. Report event-history unavailability independently from an empty list.

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
while its event remains in the web process's memory buffer**. Notifications
and their underlying history disappear when the web service restarts. They
must not be reconstructed from system logs after restart.

The existing public-IP exposure warning and unknown gateway safety indication
always take precedence over informational event notifications. Clearing history
must never suppress a current unsafe-mode warning.

### 7.2 Event history viewer

Place a collapsible **Event Log** section near the bottom of the dashboard,
before Advanced Gateway Modes. Present newest first, with timestamp, severity,
human-readable description, and a small detail view of allowlisted fields.

- Load the latest 25 events initially; permit bounded pagination of older events.
- Provide Refresh and a clear indication of whether in-memory history is enabled.
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
| `GET /api/v2/events` | Retrieve a bounded, newest-first page of sanitized in-memory events |
| `GET /api/v2/events/status` | Retrieve enabled/disabled policy, availability, and limited counts |
| `POST /api/v2/events/clear` | Clear **all** SnarkyCtl-managed in-memory event history |

The list operation supports bounded `limit` and opaque cursor parameters; it
never accepts filesystem paths, provider commands, or arbitrary queries.
Use existing HTTP Basic authentication and the private management interface.
For `POST`, enforce the existing JSON content type, `X-SnarkyCtl-Request: 1`,
Origin and Fetch Metadata restrictions before touching the in-memory buffer.
Require an explicit confirmation token/body validated by the web API, which
owns the buffer. Clear is administrative even though it cannot alter VPN mode.

The response must distinguish confirmed success from a failed clear operation.
Do not return deleted event bodies in the response.

## 9. Delete all log history

### 9.1 UI interaction

Add a clearly labeled **Delete all log history** button within the Event Log
section, with an explicit confirmation dialog explaining the effect and limits.
Do not trigger deletion merely by expanding the section or pressing Refresh.

The confirmation copy must say, in substance:

> This clears all event history held in SnarkyCtl's memory, including notifications
> derived from those events. It does not delete Linux system journals, Uvicorn
> or provider logs, VPS provider records, or other independent logs.
> Event history is never saved to disk by SnarkyCtl.

Disable repeated submissions while the action is in flight. On success, clear
the event list and any event-derived banners immediately, and show a short
non-persisted success acknowledgement. Do not write a new `HISTORY_CLEARED`
event into the just-cleared history.

### 9.2 Deletion contract

A successful clear must:

1. Erase the current web application's entire in-memory event ring, including
   previously received disconnection and recovery events.
2. Remove all event-derived notifications and dismissals maintained in the web
   application's memory, without clearing independent live safety warnings.
3. Use a clear barrier/generation so concurrently delivered or queued events
   created before the clear cannot repopulate the buffer. A late event from
   the preceding generation must be discarded rather than shown again.
4. Invalidate all cached event pages in the running web process, stale cursors,
   and event-derived banners in connected browsers on their next refresh.
5. Preserve live connection status, gateway mode, target catalogue, security
   settings, and other non-history state.
6. Return success only once the in-memory clear and invalidation are complete;
   return an explicit error rather than claiming success on failure.

Events genuinely produced **after** the clear barrier may appear as new events.
Clearing does not disable subsequent event collection; select `off` separately
for that. Do not record a `HISTORY_CLEARED` event into the emptied history.

There is no SnarkyCtl-managed on-disk event history to delete. The action must
not try to delete operating-system, provider, or unrelated application logs.

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
- Bounded memory, IPC messages, query size, and result count must prevent log-volume DoS.
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
- Inspect emitted events, local IPC messages, daemon diagnostics, HTTP responses,
  and browser state for forbidden data.
- Verify neither mode ever creates event-history files, databases, or disk queues.
- Audit Uvicorn/control-daemon diagnostic logging separately; explicitly document
  records remaining outside the history feature's control.

### Functional behavior

- A manual VPN mode change and a failed connection each generate one expected,
  sanitized event; routine status polling generates none.
- Notifications reflect severity and do not obscure current exposure warnings.
- Event history survives browser refresh and is bounded, ordered, and paginated.
- Restarting only the web service erases event history and notifications; browser
  refresh does not. Events while the web process is offline are not replayed.
- A daemon-only restart need not clear events already held by the web process.
- `off` exposes live status without retaining event history.
- Events are unavailable to unauthenticated clients and are never exposed on
  the VPS public interface.

### Delete all history

- Confirmation is mandatory; the same-origin mutation requirements are enforced.
- Clear removes all SnarkyCtl in-memory event history and derived notifications.
- A browser refresh, second browser session, or pagination request cannot restore
  events erased before the clear barrier.
- Simulate concurrent event delivery and queued IPC messages; prior events cannot
  reappear after successful deletion.
- Current safety warnings remain visible; new events after deletion work normally.
- Simulated in-memory clear failure yields an explicit error and no false
  success indication.
- Test that unrelated systemd journals and Uvicorn/provider logs are untouched.

## 12. Development increments

1. Define a strict, versioned event schema and approved event codes; write
   data-minimization and serialization tests first.
2. Implement bounded web-owned in-memory history with `off` and `memory`
   policies, including concurrency and eviction tests; no persistent storage.
3. Implement a credential-checked, best-effort Unix-domain event channel from
   the privileged daemon to the unprivileged web process, with no replay queue.
4. Add authenticated HTTP read/status/clear endpoints, a confirmed in-memory
   clear barrier, and stale-cursor invalidation.
5. Add the console Event Log viewer, notifications, and Delete all history dialog.
6. Test isolated web restart (history lost), browser refresh (history retained),
   daemon restart, producer outage, and clear-vs-delivery races.
7. Audit system-level diagnostic boundaries, update operator/API/configuration
   documentation, package tests, and perform UAT on `snarkypuss-test`.
8. Once merged to `main`, rebase `feature/auto-recovery` and replace ad-hoc
   recovery log messages with the approved event codes and notifications.

**Out of scope:** Implementing automatic recovery itself, redesigning the VPN
provider interfaces, general-purpose journal viewing, external notifications,
retention of client traffic, and changes to VPN-target persistence.
