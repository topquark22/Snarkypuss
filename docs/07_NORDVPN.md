# Snarkypuss NordVPN Guide

## Purpose

This guide covers the NordVPN-specific part of a Snarkypuss deployment. The general VPS,
WireGuard, DNS, and SnarkyCtl procedures live in the earlier numbered guides.

The reference deployment uses Ubuntu 24.04 LTS and NordVPN's NordLynx technology. NordVPN
owns the upstream tunnel, provider routing, provider firewall/Kill Switch, DNS integration,
and server selection. Snarkypuss owns the private WireGuard management path, forwarding,
private DNS, and the rule that a provider failure must never silently become Direct VPS
egress.

## 1. Install the NordVPN Linux client

Run these commands on the Linode, not on Windows.

The official installer is:

```bash
sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
```

If the NordVPN package repository is already configured, use:

```bash
sudo apt-get update
sudo apt-get install nordvpn
```

Confirm that the client is available:

```bash
nordvpn --version
nordvpn help
```

## 2. Log in on a headless Linode

Generate a Nord Account access token and run:

```bash
nordvpn login --token NORDVPN_ACCESS_TOKEN
```

Do not store the token in the repository, `/etc/snarkypuss-setup.conf`, SnarkyCtl
configuration, the destination database, or committed shell scripts.

## 3. Configure the Snarkypuss NordVPN policy

Snarkypuss includes:

```text
scripts/snarkypuss-nordvpn-configure.py
```

The helper derives the WireGuard listener port and management subnet from
`/etc/snarkypuss-setup.conf`. It then configures the reference NordVPN policy:

- NordLynx technology,
- auto-connect disabled,
- a narrow exception for the WireGuard UDP listener,
- a narrow exception for the private WireGuard management subnet, and
- Kill Switch enabled.

Keep the LISH console available before applying provider firewall changes. LISH is
independent of WireGuard, SSH, and the NordVPN firewall and is the recovery path if remote
management is interrupted.

Preview the exact NordVPN commands first:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

The dry run does not modify provider state.

After confirming independent LISH/console access, apply the policy:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --apply \
    --console-confirmed
```

`--apply` must run as root and intentionally requires `--console-confirmed`.

The helper verifies the resulting NordVPN settings and fails if it cannot confirm:

- `Technology: NordLynx`,
- Kill Switch enabled, and
- auto-connect disabled.

Existing management exceptions are treated idempotently when the installed client reports
that they are already present.

The helper does **not** connect NordVPN and does **not** perform the fail-closed acceptance
test. Those remain explicit operational steps because they require observing the real
network path.

### Equivalent provider operations

The helper performs operations equivalent to:

```bash
sudo nordvpn set technology NordLynx
sudo nordvpn set autoconnect off
sudo nordvpn allowlist add port 51820 protocol UDP
sudo nordvpn allowlist add subnet 10.8.0.0/24
sudo nordvpn set killswitch on
```

The actual port and subnet come from `/etc/snarkypuss-setup.conf`; the reference values above
are not hard-coded policy values.

Do not broadly allowlist TCP port 22 or TCP port 8443. SSH and SnarkyCtl remain private
services reached through WireGuard. Do not expose them publicly as a substitute for a
correct management-path exception.

## 4. Connect and inspect NordVPN

After the policy helper succeeds, connect normally:

```bash
sudo nordvpn connect
sudo nordvpn status
sudo nordvpn settings
```

A plain `nordvpn connect` lets NordVPN choose a recommended server.

Do not proceed to gateway activation unless the provider connection works and the Kill
Switch remains enabled.

## 5. Test fail-closed behavior

The management exceptions are acceptable only if ordinary Windows Internet traffic cannot
bypass NordVPN.

Keep LISH open during this test.

With the Snarkypuss WireGuard tunnel active, verify private management from Windows:

```powershell
Test-NetConnection 10.8.0.1 -Port 22
Test-NetConnection 10.8.0.1 -Port 8443
```

On the Linode, inspect the provider and WireGuard state:

```bash
sudo wg show wg0
sudo nordvpn status
sudo nordvpn settings
```

Then disconnect NordVPN while leaving the Kill Switch enabled:

```bash
sudo nordvpn disconnect
```

The required result is:

- private SSH over WireGuard remains reachable,
- the SnarkyCtl dashboard remains reachable,
- ordinary Internet traffic forwarded from Windows is blocked, and
- forwarded traffic does not leave through the Linode public interface.

This is the expected Locked condition.

Reconnect when the test is complete:

```bash
sudo nordvpn connect
```

If Windows Internet traffic still works directly while NordVPN is disconnected and the Kill
Switch is expected to protect it, treat that as a safety failure. Use LISH, remove the
exception responsible for the leak, and do not rely on the deployment until fail-closed
behavior is restored and retested.

## 6. Manual provider commands

Direct NordVPN commands remain useful for diagnosis and deliberate administration:

```bash
sudo nordvpn connect
sudo nordvpn status
sudo nordvpn settings
sudo nordvpn disconnect
```

A manual `nordvpn disconnect` bypasses SnarkyCtl's higher-level safety checks. Use direct
provider commands for setup and testing, not as an unnoticed substitute for SnarkyCtl's
Locked/Protected mode transitions.

When the Kill Switch is enabled, losing public Internet access after `nordvpn disconnect` is
expected. In Snarkypuss that is desirable as long as the private WireGuard management path
remains available.

## 7. NordVPN destinations in SnarkyCtl

SnarkyCtl keeps the editable NordVPN destination catalogue in root-owned SQLite, but not
every public connection target is a database row. The NordVPN adapter declares a
parameterless recommended selector, so SnarkyCtl synthesizes this built-in target:

```text
Alias: recommended
Label: Fastest available server
```

It appears in the normal connection selector and ultimately invokes a plain
`nordvpn connect`. It is not stored in SQLite, cannot be renamed or removed, and does not
appear as an editable destination.

The dashboard supports these NordVPN target forms:

| Target type | Meaning |
|---|---|
| **Fastest in country** | Let NordVPN choose a server within a selected country. |
| **Fastest in city** | Let NordVPN choose a server in a selected city within a selected country. |
| **Server group** | Connect using one of the groups reported by `nordvpn groups`. |
| **Specific server** | Pass one explicit NordVPN server identifier, such as `us9176`. |
| **Legacy configured target** | Compatibility form for an older migrated target; existing entries only. |

Country, city, and group fields are discovered live through the installed client:

```bash
nordvpn countries
nordvpn cities united_states
nordvpn groups
```

The dashboard renders those provider-backed choices generically. City is a cascading choice:
Country must be selected before the City list can be loaded. Labels shown to the user are
kept separate from the stored machine values.

A group is whatever category the installed NordVPN client currently reports. Some groups may
represent account-specific or specialty services. Selecting a group does not add another IP
or server field; SnarkyCtl passes the selected group to NordVPN and NordVPN decides whether
that target is available for the logged-in account. If it is not, the connection fails with
a controlled provider error.

**Specific server** deliberately remains an advanced text field. SnarkyCtl applies basic
structural safety limits but does not duplicate NordVPN's semantic validation rules. For
example, `us9176` can be stored and passed as the server identifier. A nonexistent or
otherwise invalid identifier is allowed to fail when NordVPN performs the connection.
SnarkyCtl does not enumerate exact servers in this release.

For new destinations, the dashboard proposes a friendly label and a unique alias from the
selected provider labels. Manual edits to either value are preserved.

`Legacy configured target` exists only so old imported values remain usable. Existing legacy
entries can be connected, changed to a modern target type, or removed. The dashboard does not
offer Legacy when adding a new destination.

Provider choices can change independently of Snarkypuss. If a saved provider-backed choice
disappears from current discovery results, the destination manager never silently changes its
selector to another value. It normally cleans up unavailable persisted entries automatically;
if automatic cleanup cannot complete, the administrator can remove or replace the entry.

## 8. What the SnarkyCtl NordVPN adapter does

The privileged runtime adapter deliberately supports only a narrow command surface
equivalent to:

```text
/usr/bin/nordvpn status
/usr/bin/nordvpn settings
/usr/bin/nordvpn set killswitch on|off
/usr/bin/nordvpn connect <validated selector arguments>
/usr/bin/nordvpn disconnect
```

This is separate from the one-time `snarkypuss-nordvpn-configure.py` setup helper. The setup
helper establishes the provider policy and management exceptions; the SnarkyCtl adapter
performs bounded runtime operations after deployment.

The browser never supplies arbitrary shell commands. Target aliases are resolved against the
trusted catalogue and provider selector fields are validated before the fixed NordVPN
executable is invoked.

Dynamic option discovery follows the same privilege boundary. The unprivileged web process
requests a schema-declared kind, field, and dependency context from the control daemon; only
the NordVPN adapter executes `countries`, `cities`, or `groups`. Provider output is bounded,
parsed, and returned as separate machine values and display labels.

For a city target, the adapter supplies both the validated country and city to
`nordvpn connect`. For a Specific server target, the adapter passes the validated text value
unchanged as the one server argument. Provider command failures remain available as
structured API errors, while the dashboard presents a shorter user-facing failure message.

## 9. NordVPN and Snarkypuss gateway modes

SnarkyCtl translates provider state into four effective modes:

- **Protected VPN** — leak protection enabled and NordVPN connected.
- **Locked** — leak protection enabled and NordVPN disconnected; public forwarding blocked.
- **Direct VPS** — exceptional explicit mode with provider leak protection disabled and
  traffic leaving through the VPS public connection.
- **Unknown** — provider state cannot be established confidently; do not assume protection.

Direct VPS must never be an automatic response to a failed NordVPN connection. If a Direct
transition fails after disabling the Kill Switch, the control daemon attempts to restore
leak protection.

## 10. Troubleshooting

Start with:

```bash
sudo nordvpn status
sudo nordvpn settings
ip link show nordlynx
snarkyctl status
```

If initial policy setup fails, preview it again with:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

If the installed NordVPN client's command names or output differ from the helper's supported
forms, inspect:

```bash
nordvpn help
man nordvpn
```

If NordVPN connects but WireGuard management disappears, review the management exceptions
and use LISH for recovery. If Internet works through the Linode public IP when Protected VPN
was expected, stop using the connection for protected traffic and follow the wrong-public-IP
procedure in [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

## 11. Provider-specific safety rules

For the reference NordVPN deployment:

- Keep the Kill Switch enabled for normal operation.
- Keep LISH available while changing provider firewall/allowlist policy.
- Use the setup helper rather than hand-building broader exceptions.
- Verify fail-closed forwarding after every material provider-policy change.
- Do not expose SSH or SnarkyCtl publicly to work around a provider firewall problem.
- Keep NordVPN access tokens out of Git and unrelated configuration files.
- Verify the observed public exit address after provider changes.
- Treat Unknown protection state conservatively.

For general symptoms, return to [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

## Official NordVPN references

NordVPN changes its Linux client independently of Snarkypuss. When syntax differs from the
installed examples, consult the current provider documentation:

- Linux installation and CLI reference:
  https://support.nordvpn.com/hc/en-us/articles/20196094470929-How-to-install-the-NordVPN-app-on-Linux-distributions
- Headless token login:
  https://support.nordvpn.com/hc/en-us/articles/20286980309265-How-to-log-in-to-NordVPN-without-a-GUI-using-a-token
- Linux Kill Switch behavior:
  https://support.nordvpn.com/hc/en-us/articles/19509682644369-NordVPN-Kill-Switch-how-does-it-work
- Linux allowlist/split-tunneling behavior:
  https://support.nordvpn.com/hc/en-us/articles/19618692366865-What-is-Split-Tunneling-and-how-to-use-it-with-NordVPN
