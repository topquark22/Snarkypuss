# Snarkypuss VPS and Networking Setup Guide

## Purpose

This guide sets up the VPS and networking layer of a new Snarkypuss deployment. It covers:

- creating and preparing the Linode,
- keeping independent LISH recovery access available,
- installing the base gateway packages,
- creating the Windows-to-Linode WireGuard tunnel,
- generating the managed gateway configuration,
- installing and configuring NordVPN,
- activating forwarding and NAT with automatic rollback,
- verifying the private management path and protected Internet path, and
- restricting public administrative access after the private path is proven.

The gateway generator also creates the Snarkypuss-owned private DNS configuration and
`snarkypuss-dns.service`. The next numbered guide,
[02_SETUP_DNS.md](02_SETUP_DNS.md), explains DNS in detail and performs the full DNS
verification.

After networking and DNS are working, continue with
[03_SETUP_SNARKYCTL.md](03_SETUP_SNARKYCTL.md).

The tested reference deployment uses:

- Windows 11 as the trusted client,
- WireGuard as the private client-to-VPS tunnel,
- Ubuntu 24.04 LTS on the VPS,
- Linode as the VPS host,
- NordVPN as the upstream VPN provider,
- a dedicated `dnsmasq` instance for DNS on the private tunnel, and
- SnarkyCtl for private status and control.

These are the tested reference choices, not architectural requirements.

## Before you begin

You need:

- an **Akamai Cloud account** with access to Linode,
- a **NordVPN account**,
- a **NordVPN access token** suitable for logging in from a headless Linux system,
- WireGuard for Windows, and
- a current Snarkypuss source checkout on the Linode so the `scripts/` and `config/` files
  used below are available.

Keep the NordVPN access token private. Do not put it in the Snarkypuss repository,
SnarkyCtl configuration, or destination database.

### Create the Linode

In **Akamai Cloud Manager**:

1. Select **Linodes**.
2. Select **Create Linode**.
3. Choose **Ubuntu 24.04 LTS** as the image.
4. Choose the smallest Shared CPU plan suitable for the reference deployment: **1 GB RAM,
   1 shared vCPU, and 25 GB storage**.
5. Choose the region you want the VPS to occupy.
6. Set a root password.
7. Create the Linode.
8. Record its public IPv4 address.

Pricing and available plan names can change, so use the price shown in Cloud Manager rather
than relying on an old price quoted in documentation.

### Open LISH before changing networking

Initial VPS-side setup should be performed through the **LISH web console** rather than an
ordinary SSH session. LISH does not depend on WireGuard, NordVPN, SSH routing, or the VPS
firewall remaining usable.

In Akamai Cloud Manager:

1. Open **Linodes**.
2. Select the Snarkypuss Linode.
3. Select **Launch LISH Console**.
4. Log in as `root` using the root password created for the Linode.

Keep the LISH window available until WireGuard, private SSH, provider fail-closed behavior,
and the final firewall policy have all been tested.

Unless a step is explicitly labelled **Windows**, Linux commands in this guide are entered on
the Linode, initially through LISH.

## Setup sequence

Complete this guide in order:

1. Prepare the VPS and recovery access.
2. Run the read-only gateway preflight.
3. Install the base gateway packages.
4. Create the Windows WireGuard tunnel and copy its public key to the Linode.
5. Generate the Linode WireGuard, DNS, and forwarding configuration.
6. Finish the Windows WireGuard tunnel configuration.
7. Install and configure NordVPN.
8. Activate the gateway with automatic rollback enabled.
9. Verify the Windows-to-Linode path and protected Internet egress.
10. Test fail-closed behavior.
11. Restrict public administrative access in the Linode Firewall.
12. Continue with [02_SETUP_DNS.md](02_SETUP_DNS.md).

Do not install SnarkyCtl until the private WireGuard path and protected Internet path have
been tested successfully.

## Reference network values

The current reference configuration uses:

| Setting | Reference value |
|---|---|
| WireGuard interface | `wg0` |
| Private WireGuard network | `10.8.0.0/24` |
| Linode WireGuard address | `10.8.0.1/24` |
| Windows WireGuard address | `10.8.0.2` |
| WireGuard listen port | `51820/UDP` |
| WireGuard firewall mark | `0xe1f1` |
| NordVPN NordLynx interface | `nordlynx` |
| SnarkyCtl HTTPS address | `10.8.0.1` |
| SnarkyCtl HTTPS port | `8443/TCP` |

If you deliberately use different values, keep them consistent across WireGuard, the
Snarkypuss setup file, provider bypass policy, DNS, SnarkyCtl, and firewall rules.

## 1. Prepare the VPS and recovery access

In LISH, confirm the operating system and identify the default public interface:

```bash
cat /etc/os-release
ip route show default
```

The supported reference system is Ubuntu 24.04 LTS.

Before making networking changes:

- keep LISH open,
- record the Linode public IPv4 address,
- note the public interface shown by `ip route show default`,
- make sure the current Snarkypuss source checkout is available, and
- consider taking a Linode snapshot before converting an existing machine.

Do not make public SSH your only recovery path during setup. LISH is the fallback if a
WireGuard, provider, routing, or firewall change interrupts network access.

The final public firewall will allow the WireGuard UDP listener. SnarkyCtl HTTPS must not be
exposed publicly.

## 2. Run the gateway preflight

From the Snarkypuss source checkout on the Linode, run:

```bash
sudo scripts/snarkypuss-preflight.sh \
    --tunnel-interface wg0 \
    --client-cidr 10.8.0.0/24 \
    --listen-port 51820
```

The preflight is read-only. It checks the host conditions needed by later steps without
installing packages, starting services, changing routes, altering firewall rules, or enabling
forwarding.

The result types are:

| Result | Meaning |
|---|---|
| `PASS` | The structural check succeeded. |
| `INFO` | Informational state for review. |
| `WARN` | The condition may be acceptable but deserves attention. |
| `FAIL` | A required structural check failed. |

Exit status `0` means no structural check failed. Exit status `1` means at least one check
failed. Exit status `2` means the command-line arguments were invalid.

A successful preflight does **not** prove privacy or leak protection. Those tests occur after
activation.

## 3. Install the base gateway packages

Review the package installation first:

```bash
scripts/snarkypuss-install.sh --dry-run
```

Then install the base gateway packages:

```bash
sudo scripts/snarkypuss-install.sh
```

The installer supplies the provider-neutral WireGuard, DNS, routing, firewall, and diagnostic
dependencies used by the gateway. It does not install, log in to, connect, or configure
NordVPN.

For DNS, the installer installs `dnsmasq-base`, which provides `/usr/sbin/dnsmasq` without
installing Ubuntu's stock `dnsmasq.service` or making Snarkypuss depend on
`/etc/dnsmasq.conf`. The Snarkypuss DNS service is generated later and is not started by the
package-install step.

## 4. Create the WireGuard tunnel on Windows and copy its public key

**This section is done on the Windows PC, not in LISH.**

Install WireGuard for Windows if necessary. Then:

1. Open **WireGuard**.
2. Select **Add Tunnel**.
3. Select **Add empty tunnel...**.
4. Name the tunnel `snarkypuss`.
5. WireGuard automatically generates a private key and corresponding public key.
6. Leave the generated private key on Windows.
7. Copy the displayed **Public key**.

The Windows private key must never be copied to the Linode.

Return to the LISH console and create the root-only file that will contain the Windows
public key:

```bash
sudo install -m 0600 /dev/null /root/snarkypuss-client.pub
sudoedit /root/snarkypuss-client.pub
```

Paste the Windows WireGuard public key as one line, save the file, and exit the editor.

Do not activate the Windows tunnel yet. The Linode must generate its own WireGuard key and
configuration first.

## 5. Generate the Linode gateway configuration

The **gateway** in this documentation is the Linode VPS itself. There is no separate gateway
machine to create.

Copy the non-secret setup template outside the repository:

```bash
sudo install -m 0600 \
    config/snarkypuss-setup.conf.example \
    /etc/snarkypuss-setup.conf
sudoedit /etc/snarkypuss-setup.conf
```

For the reference deployment, the file contains:

```ini
[gateway]
tunnel_interface = wg0
server_address = 10.8.0.1/24
listen_port = 51820
client_address = 10.8.0.2/32
protected_egress_interface = nordlynx
tunnel_fwmark = 0xe1f1
persistent_keepalive = 25
client_public_key_file = /root/snarkypuss-client.pub
dns_upstreams = 1.1.1.1, 1.0.0.1
```

This file must never contain a WireGuard private key. DNS upstreams are literal IP addresses
rather than hostnames.

Validate the input and preview the changes:

```bash
sudo scripts/snarkypuss-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

If the dry run succeeds, generate the managed files:

```bash
sudo scripts/snarkypuss-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --apply
```

The command prints the **Linode WireGuard public key**. Copy that one-line public key into a
temporary Notepad document on Windows. You will use it in Section 6.

Do **not** copy `/etc/wireguard/wg0.private.key` to Windows. That is the Linode's private key
and must remain on the Linode.

The generator creates these managed files:

| Path | Purpose |
|---|---|
| `/etc/wireguard/wg0.private.key` | Persistent Linode WireGuard private key |
| `/etc/wireguard/wg0.conf` | Linode WireGuard interface and Windows peer |
| `/etc/snarkypuss/dnsmasq.conf` | Snarkypuss-owned private DNS listener and upstreams |
| `/etc/systemd/system/snarkypuss-dns.service` | Dedicated private DNS service and WireGuard dependency |
| `/etc/sysctl.d/90-snarkypuss.conf` | Persistent IPv4 forwarding setting |

Generating these files does not by itself make the forwarding path live. Live changes are
made in Section 8 through the activation script with automatic rollback.

## 6. Finish the WireGuard tunnel on Windows

**This entire section is done on the Windows PC in the WireGuard application.**

Return to the `snarkypuss` tunnel created in Section 4:

1. Open **WireGuard**.
2. Select the `snarkypuss` tunnel.
3. Select **Edit**.
4. Keep the private key WireGuard generated earlier.
5. Complete the configuration in this form:

```ini
[Interface]
PrivateKey = YOUR_EXISTING_WINDOWS_PRIVATE_KEY
Address = 10.8.0.2/24
DNS = 10.8.0.1

[Peer]
PublicKey = LINODE_WIREGUARD_PUBLIC_KEY
Endpoint = LINODE_PUBLIC_IPV4_ADDRESS:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Replace only the placeholders:

- `YOUR_EXISTING_WINDOWS_PRIVATE_KEY` is the key already generated in this Windows tunnel.
- `LINODE_WIREGUARD_PUBLIC_KEY` is the public key printed by the configuration generator in
  Section 5.
- `LINODE_PUBLIC_IPV4_ADDRESS` is the public IPv4 address shown by Akamai Cloud Manager.

Select **Save**. Do not activate the tunnel yet.

Only public keys are exchanged between the two systems. The Windows private key stays on
Windows and the Linode private key stays on the Linode.

### Add the private `snarkypuss` hostname

Still on Windows, open **Notepad as Administrator** and edit:

```text
C:\Windows\System32\drivers\etc\hosts
```

Add:

```text
10.8.0.1 snarkypuss
```

Save the file.

Later, with WireGuard active, Windows will be able to use:

```text
ssh root@snarkypuss
https://snarkypuss:8443/
```

## 7. Install and configure NordVPN

Run these commands on the Linode.

Install the official NordVPN Linux client:

```bash
sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
```

If the NordVPN package repository is already configured, the client can instead be installed
or updated with:

```bash
sudo apt-get update
sudo apt-get install nordvpn
```

Authenticate the headless Linode using your NordVPN access token:

```bash
nordvpn login --token NORDVPN_ACCESS_TOKEN
```

SnarkyCtl does not store this token.

Configure the reference provider settings:

```bash
sudo nordvpn set technology NordLynx
sudo nordvpn set killswitch on
sudo nordvpn set autoconnect off
```

The Kill Switch is deliberately enabled **before** Snarkypuss starts forwarding Windows
traffic. Auto-connect remains off during initial setup so provider state changes are
deliberate and visible.

The private WireGuard listener and management subnet must remain reachable when the Kill
Switch is active. Recent NordVPN Linux clients use `allowlist`:

```bash
sudo nordvpn allowlist add port 51820 protocol UDP
sudo nordvpn allowlist add subnet 10.8.0.0/24
```

Some installed versions use the older `whitelist` spelling. Use the spelling accepted by the
installed client.

Inspect the effective settings:

```bash
sudo nordvpn settings
```

Then connect and inspect the provider state:

```bash
sudo nordvpn connect
sudo nordvpn status
```

Do not continue to gateway activation unless the Kill Switch is enabled and the provider
connection is working.

For the full provider-specific explanation, destination selectors, and management-bypass
safety test, see [07_NORDVPN.md](07_NORDVPN.md).

## 8. Activate the gateway with automatic rollback

Activation is the first step that changes live forwarding and service state.

Before applying it, confirm that:

- LISH is still available,
- NordVPN is connected,
- NordVPN leak protection is enabled,
- the configured protected egress interface matches the actual provider interface,
- the Windows WireGuard tunnel configuration has been saved, and
- the generated WireGuard and dedicated DNS files exist.

Review the activation plan:

```bash
sudo scripts/snarkypuss-activate.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

Apply it with a rollback timer:

```bash
sudo scripts/snarkypuss-activate.py \
    --config /etc/snarkypuss-setup.conf \
    --apply \
    --console-confirmed \
    --provider-leak-protection-confirmed \
    --rollback-after 120
```

The activation process captures the previous firewall, forwarding, and relevant service
state before changing anything. It schedules a transient systemd rollback timer, creates the
dedicated Snarkypuss forwarding/NAT chains, enables IPv4 forwarding at runtime, and starts
the managed WireGuard and `snarkypuss-dns.service` services.

On a legacy Snarkypuss installation, activation also cuts over from the recognized old
`dnsmasq.service` configuration to `snarkypuss-dns.service`. It refuses to disable an
unrecognized administrator-owned dnsmasq service.

The script prints an activation token. **Do not confirm the activation yet.** First test the
real Windows client path.

If activation itself fails, the script attempts to restore the captured state. Use LISH to
inspect the failure rather than disabling safety controls blindly.

## 9. Verify the Windows client path before confirming activation

On Windows, activate the `snarkypuss` WireGuard tunnel.

On the Linode, check WireGuard:

```bash
sudo wg show wg0
```

Look for:

- the Windows peer,
- a recent handshake, and
- increasing received and transmitted byte counters when Windows generates traffic.

From Windows, verify that the private Linode address is reachable:

```powershell
ping 10.8.0.1
```

If private SSH is already installed and allowed on the Linode, test it through the private
path:

```powershell
ssh root@snarkypuss
```

Then test ordinary Internet access from Windows and check the observed public IP using a
normal HTTPS IP-check site or service. The observed public address must be the NordVPN exit
address, not the Linode's ordinary public address and not the Windows connection's home
address.

Run the structural verifier on the Linode:

```bash
sudo scripts/snarkypuss-verify.sh \
    --tunnel-interface wg0 \
    --client-cidr 10.8.0.0/24 \
    --vps-public-ip LINODE_PUBLIC_IPV4_ADDRESS
```

The verifier checks WireGuard, forwarding, DNS listener state, firewall/NAT references,
default routing, and VPS-originated public egress. Its public-IP check originates on the VPS,
so it does not replace the Windows client-side egress test.

If all required checks succeed, confirm the activation using the exact token printed in
Section 8:

```bash
sudo scripts/snarkypuss-activate.py --confirm ACTIVATION_TOKEN
```

Confirmation cancels the rollback timer and persists the accepted firewall state.

If the activation is not confirmed before the timer expires, the previous firewall,
forwarding, and service state is restored automatically.

## 10. Test fail-closed behavior

A working VPN connection is not enough. You must also verify what happens when NordVPN is
intentionally disconnected while its Kill Switch remains enabled.

Keep all of these available during the test:

- the LISH console,
- the Windows WireGuard tunnel, and
- preferably an existing private SSH session through WireGuard.

Disconnect NordVPN on the Linode:

```bash
sudo nordvpn disconnect
```

The correct result is:

- the WireGuard tunnel remains established,
- private SSH through WireGuard remains reachable,
- private management traffic remains reachable,
- ordinary Internet traffic forwarded from Windows is blocked, and
- Windows traffic does not escape through the Linode's real public address.

Reconnect NordVPN after the test:

```bash
sudo nordvpn connect
```

If WireGuard management disappears, use LISH and correct the NordVPN allowlist/bypass policy.
If Windows Internet traffic continues directly through the Linode while NordVPN is
disconnected, treat that as a safety failure and correct it before continuing.

**Locked is the safe fallback.** Provider failure must never silently become Direct VPS
operation.

## 11. Restrict public administrative access

Only do this after the private WireGuard path has been proven from a fresh Windows session.

In **Akamai Cloud Manager**, open the Linode Firewall attached to the Snarkypuss VPS and
review the inbound rules.

For the reference deployment:

- allow `51820/UDP` publicly so the Windows WireGuard client can reach the Linode,
- remove public `22/TCP` access after private SSH through WireGuard has been proven, and
- keep `8443/TCP` closed to the public Internet.

Keep LISH open while changing the cloud firewall. An incorrect rule must not remove your last
administrative path.

The Linode Firewall is an outer layer of protection; it does not replace correct service
binding on the VPS. SnarkyCtl must later bind only to the private WireGuard address, never to
`0.0.0.0`, `[::]`, or the Linode public address.

## VPS networking setup complete

At this point:

- Windows can establish the private WireGuard tunnel,
- private management access works through WireGuard,
- NordVPN supplies the protected Internet path,
- fail-closed behavior has been tested, and
- public administrative exposure has been reduced.

Continue with [02_SETUP_DNS.md](02_SETUP_DNS.md) to validate the private DNS service in
detail. After DNS is working, continue with
[03_SETUP_SNARKYCTL.md](03_SETUP_SNARKYCTL.md).
