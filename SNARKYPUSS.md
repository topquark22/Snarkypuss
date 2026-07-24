# Snarkypuss Private VPN Gateway: Technical Reference

## Purpose and scope

This is the technical implementation reference for the **Snarkypuss** private VPN gateway.
For the project overview, safety model, and the relationship between Snarkypuss and its
SnarkyCtl management utility, begin with [README.md](README.md).

## Quick start: read-only gateway checks

The repository includes two provider-neutral scripts for inspecting the VPS without changing
it. They do not install packages, write configuration, change routes or firewall rules,
start services, or enable forwarding.

Run both scripts from the root of a Snarkypuss source checkout:

```bash
cd ~/snarkyctl
```

Use `--help` to see every option:

```bash
scripts/snarkypuss-preflight.sh --help
scripts/snarkypuss-verify.sh --help
```

### Before configuring the gateway

Run the preflight on a new VPS before following the manual installation sections:

```bash
sudo scripts/snarkypuss-preflight.sh \
    --tunnel-interface wg0 \
    --client-cidr 10.8.0.0/24 \
    --listen-port 51820
```

Running as root is recommended so service and firewall inspection is complete, but the
script remains read-only. It reports the operating system, required and optional commands,
systemd, the default route, interface-name availability, current forwarding state, UDP-port
use, SSH, and the DNS service unit.

Missing packages that a later installation step can supply are warnings. A missing core host
capability is a failure. The final warning to confirm VPS console access is intentional:
future configuration increments will make network changes that could interrupt SSH.

### After configuring the gateway

After completing this reference guide, run:

```bash
sudo scripts/snarkypuss-verify.sh \
    --tunnel-interface wg0 \
    --client-cidr 10.8.0.0/24 \
    --vps-public-ip VPS_PUBLIC_IPV4_ADDRESS
```

Replace `VPS_PUBLIC_IPV4_ADDRESS` with the VPS's real public address. Supplying it lets the
verifier issue a prominent warning when observed egress clearly exposes that address. The
address is used only for comparison and is not stored or transmitted separately.

The verifier checks:

- The tunnel interface, state, and IPv4 address.
- IPv4 forwarding.
- WireGuard recognition and peer handshakes.
- DNS service and UDP listener state.
- Observable firewall and NAT references.
- The default route.
- Public egress through a certificate-verified HTTPS request.

### Reading the result

Both scripts print `PASS`, `INFO`, `WARN`, and `FAIL` records:

| Exit status | Meaning |
|---|---|
| `0` | No structural check failed; warnings may still require attention. |
| `1` | At least one structural gateway check failed. |
| `2` | The command-line arguments were invalid. |

Read the individual records; do not treat exit status 0 as proof that the entire client path
is private. The verifier's public-IP request originates on the VPS. A different IP is
consistent with upstream VPN egress but does not prove the forwarded client path, while a
failed request may mean Locked mode or an unrelated connectivity problem.

Complete the client-side external-IP and DNS-leak tests in Sections 11 and 12 before trusting
the gateway. Never use `curl -k` to suppress a certificate failure.

## Install packages and generate base configuration

After the read-only preflight succeeds, iteration 2 can install the base gateway packages and
generate configuration files. These tools remain provider-neutral: they do not install,
authenticate, connect, or configure NordVPN or another upstream VPN provider.

### Install the base packages

Review the fixed package command without changing the VPS:

```bash
scripts/snarkypuss-install.sh --dry-run
```

Then install the packages:

```bash
sudo scripts/snarkypuss-install.sh
```

The installer runs `apt-get update` followed by a noninteractive installation of the
reviewed package list. Use `--skip-update` only when the apt metadata is already current.
To avoid exposing a default DNS listener, a newly installed `dnsmasq` unit is stopped and
disabled until configuration is ready. If dnsmasq was already installed, its existing service
state is preserved. The installer does not write Snarkypuss configuration or activate gateway
routing.

The supported platform is Ubuntu 24.04. The `--allow-unsupported` option exists for an
administrator who has independently reviewed the package names; it is not a claim of support
for another distribution.

### Prepare the non-secret setup input

The generator reads an INI file containing only known fields. Copy the example:

```bash
sudo install -m 0600 \
    config/snarkypuss-setup.conf.example \
    /etc/snarkypuss-setup.conf
sudoedit /etc/snarkypuss-setup.conf
```

The setup file contains the private tunnel and protected-provider interface names, the
WireGuard firewall mark used by provider routing policy, server and client tunnel addresses,
UDP listen port, DNS upstream IP addresses, and the path to a file containing the **client's
public WireGuard key**. It must never contain either the client or server private key.

Generate the client key in the WireGuard client application, copy only its public key, and
place that single line on the VPS:

```bash
sudo install -m 0600 /dev/null /root/snarkypuss-client.pub
sudoedit /root/snarkypuss-client.pub
```

The default example expects that path. Absolute paths are required, unknown settings are
rejected, DNS hostnames are rejected in favor of literal IP addresses, and the client address
must belong to the server tunnel network.

### Preview and generate the files

Always validate with a dry run first:

```bash
sudo scripts/snarkypuss-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

The dry run validates all input and lists its intended files without generating a key,
creating a directory, or writing anything. Apply the reviewed plan explicitly:

```bash
sudo scripts/snarkypuss-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --apply
```

A fresh apply generates and reports the server WireGuard public key, then creates:

| File | Mode | Purpose |
|---|---:|---|
| `/etc/wireguard/wg0.private.key` | `0600` | Persistent generated server private key |
| `/etc/wireguard/wg0.conf` | `0600` | Server interface and client peer |
| `/etc/dnsmasq.d/snarkypuss.conf` | `0644` | Tunnel-bound DNS listener and upstreams |
| `/etc/systemd/system/dnsmasq.service.d/snarkypuss.conf` | `0644` | Starts dnsmasq only after the private WireGuard interface is available |
| `/etc/sysctl.d/90-snarkypuss.conf` | `0644` | Persistent IPv4-forwarding setting |

The exact WireGuard filenames follow `tunnel_interface`. The private-key directory is mode
`0700`. Repeated application preserves the existing server key and leaves identical files
unchanged. Before replacing a changed file, the generator creates a timestamped
`.bak.YYYYMMDDTHHMMSSZ` copy in the same directory.

The generated systemd drop-in declares `Requires=` and `After=` for the configured
`wg-quick@` service. This prevents dnsmasq from trying to bind its tunnel-only address before
WireGuard creates the interface during boot. Activation runs `systemctl daemon-reload` before
starting either service.

### Apply the startup-order fix to an existing managed gateway

A gateway configured before this drop-in was introduced can add it without rerunning
activation or changing live firewall and routing state. From an updated source checkout, run:

```bash
cd ~/snarkyctl
git pull

sudo scripts/snarkypuss-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --apply

sudo systemctl daemon-reload
sudo systemctl restart dnsmasq.service
```

Verify both services, the effective unit definition, and DNS resolution:

```bash
systemctl cat dnsmasq.service
systemctl is-active wg-quick@wg0.service dnsmasq.service
dig @10.8.0.1 example.com
```

The effective dnsmasq unit must show
`Requires=wg-quick@wg0.service` and `After=wg-quick@wg0.service`. Both services should
report `active`, and the DNS query should return an answer. A new activation is not required
for this correction. Test one subsequent reboot while independent VPS console access remains
available.

If an existing WireGuard configuration is found without the separately managed private-key
file, the generator refuses to continue rather than silently rotating the server identity.
This is particularly important on an existing manually configured gateway: use
`--dry-run`, inspect the result, and plan key migration before applying it.

Configuration generation does **not** load the sysctl file, start or enable WireGuard or
dnsmasq, add routes, create NAT or firewall rules, or change upstream VPN state. Those
activation and rollback operations belong to iteration 3. When using generated files, do not
overwrite them with the manual file-creation examples later in this reference; use those
sections to understand and verify their contents.

---

## Migrate an existing manually configured gateway

Do not reconstruct an existing gateway by hand. The migration tool reads the current
WireGuard and dnsmasq files, preserves the server identity and single client peer, and
prepares the managed files used by the generator.

First perform a read-only audit. The protected egress interface is explicit because silently
guessing it could weaken the provider leak-protection policy:

```bash
sudo scripts/snarkypuss-migrate.py \
    --audit \
    --tunnel-interface wg0 \
    --protected-egress-interface nordlynx
```

The audit reports the settings it can preserve and any legacy WireGuard lifecycle hooks. It
validates the private key but never prints it. If literal dnsmasq `server=` entries cannot be
discovered, supply them explicitly with, for example,
`--dns-upstreams 1.1.1.1,1.0.0.1`.

Prepare the migration only after reviewing the audit:

```bash
sudo scripts/snarkypuss-migrate.py \
    --prepare \
    --tunnel-interface wg0 \
    --protected-egress-interface nordlynx
```

Preparation creates a mode-`0700` backup below
`/var/backups/snarkypuss/migration-<UTC timestamp>/`, including a checksummed manifest
and an `iptables-save` snapshot when available. It then separates the existing server
private key, stores the client public key, creates `/etc/snarkypuss-setup.conf`, and runs the
normal generator. Existing `PostUp`, `PostDown`, `PreUp`, and `PreDown` commands are
reported but deliberately omitted from the managed WireGuard file.

Preparation does not stop or start a service and does not change live forwarding, routes,
firewall rules, sysctl values, or provider state. The currently loaded gateway therefore
continues running until the separate activation procedure below. If generation fails, the
tool automatically restores the captured files.

Before activation, inspect the backup and generated files. A file-only restoration is:

```bash
sudo scripts/snarkypuss-migrate.py \
    --restore /var/backups/snarkypuss/migration-YYYYMMDDTHHMMSSZ
```

Restore does not change live services or networking. If activation has already occurred, use
the activation token and `snarkypuss-rollback.py` for runtime rollback before restoring
files.

---

## Activate forwarding with automatic rollback

Activation is deliberately separate from configuration generation. Before continuing:

1. Confirm that independent VPS console access works.
2. Connect and configure the upstream VPN provider.
3. Verify that its kill switch or equivalent fail-closed policy is enabled.
4. Verify that `protected_egress_interface` names the interface created by that provider.
5. Verify that `tunnel_fwmark` matches the provider policy that exempts the private
   WireGuard transport from the upstream tunnel.

The base activation script does not decide whether the provider is Protected, Locked, or in
an explicitly selected Direct VPS state. It installs generic forwarding and NAT so traffic
follows provider-managed routing. This preserves SnarkyCtl's provider-neutral mode model.

### Review the activation plan

```bash
sudo scripts/snarkypuss-activate.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

The plan makes no changes. It identifies the private network and interfaces and describes
the proposed forwarding and NAT behavior.

### Apply with a rollback timer

Only after checking console access and provider leak protection, run:

```bash
sudo scripts/snarkypuss-activate.py \
    --config /etc/snarkypuss-setup.conf \
    --apply \
    --console-confirmed \
    --provider-leak-protection-confirmed \
    --rollback-after 120
```

Before its first network change, the script stores a root-only activation record and
schedules a transient systemd rollback timer. It then:

- Replaces only the dedicated `SNARKYPUSS_FORWARD` and `SNARKYPUSS_NAT` chains.
- Accepts forwarded traffic arriving from the configured private tunnel.
- Masquerades the private client network on the egress selected by provider routing.
- Enables IPv4 forwarding at runtime.
- Enables and starts the configured `wg-quick@` unit and `dnsmasq`.
- Leaves `INPUT`, `OUTPUT`, routes, policy-routing tables, provider firewall rules, and
  provider commands untouched.

The script prints a random activation token. Before the timer expires, verify the private
tunnel from another session and run the read-only verifier. If access and egress are correct,
confirm using the exact printed token:

```bash
sudo scripts/snarkypuss-activate.py --confirm ACTIVATION_TOKEN
```

Confirmation cancels the timer and runs `netfilter-persistent save`. Firewall rules are not
made persistent before confirmation. If confirmation never arrives, the timer restores the
complete pre-activation firewall snapshot, previous runtime forwarding value, and previous
active/enabled state of WireGuard and dnsmasq.

Activation records are mode `0600` beneath `/var/lib/snarkypuss/activations/`. They
contain firewall and service state but no WireGuard private key.

### Roll back a confirmed activation

Retain the printed token. A confirmed activation can later be reversed explicitly:

```bash
sudo scripts/snarkypuss-rollback.py \
    --token ACTIVATION_TOKEN \
    --force
```

A forced rollback restores the complete firewall snapshot and persistent rules file captured
before activation, as well as the former forwarding and service states. Because it restores a
complete snapshot, firewall changes made after that activation are discarded. Review current
firewall state and arrange console access before forcing a later rollback.

The rollback protects against accidental lockout; it cannot prove that an upstream provider's
kill switch is correct. With provider-managed routing, a missing or disabled provider kill
switch can expose the VPS public IP. Do not pass
`--provider-leak-protection-confirmed` until that policy has actually been tested.

---

---

The reference deployment routes traffic as follows:

```text
Home PC
    ↓
WireGuard tunnel
    ↓
Personal VPS (Linode)
    ↓
NordVPN
    ↓
Internet
```

Goals:

* Hide Internet traffic from the local ISP.
* Eliminate dependence on commercial VPN software running on the PC.
* Permit centralized DNS filtering.
* Allow secure remote administration over WireGuard.
* Decouple administrative access from a changing home IP address.
* Prevent DNS leaks.
* Support multi-hop VPN operation.

This guide assumes:

* Windows 11 client.
* Ubuntu 24.04 LTS VPS.
* Linode VPS.
* NordVPN subscription.

---

# 1. Create a Linode VPS

Create an account with Linode. It is very inexpensive ($5 per month or so.)

Recommended VPS:

| Setting | Value            |
| ------- | ---------------- |
| Region  | Dallas, TX       |
| Image   | Ubuntu 24.04 LTS |
| Type    | Shared CPU       |
| RAM     | 1 GB minimum     |

Choose:

```text
Ubuntu 24.04 LTS
```

Set:

```text
Root password
```

Deploy the VPS.

Record:

```text
Public IPv4 address

---

# 2. Initial Login

From Windows:

```powershell
ssh root@VPS_IP
```

Example:

```powershell
ssh root@VPS_PUBLIC_IPV4_ADDRESS
```

Update packages:

```bash
apt update
apt upgrade -y
```

Install useful tools:

```bash
apt install -y \
    wireguard \
    dnsmasq \
    iptables-persistent \
    tcpdump \
    curl \
    vim \
    net-tools \
    nftables \
    traceroute \
    dnsutils
```

---

# 3. Install NordVPN

Install:

```bash
sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
```

Add root to NordVPN group:

```bash
usermod -aG nordvpn root
```

Log in:

```bash
nordvpn login
```

Open the displayed URL in a browser. Log in and get your NordVPN access token. You will need it for the next step.

Connect:

```bash
nordvpn connect
```

Example:

```bash
nordvpn connect Czech_Republic
```

Verify:

```bash
nordvpn status
```

---

# 4. Configure NordVPN

Recommended settings:

```bash
nordvpn set technology nordlynx
nordvpn set firewall on
nordvpn set killswitch on
nordvpn set autoconnect off
```

Allow WireGuard subnet:

```bash
nordvpn whitelist add subnet 10.8.0.0/24
```

Verify the safety-relevant settings:

```bash
nordvpn settings
```

The output must report at least:

```text
Firewall: enabled
Kill Switch: enabled
```

With Kill Switch enabled, a manual or unexpected NordVPN disconnection blocks ordinary Internet access instead of exposing the VPS public IP. The WireGuard management path must remain reachable through the configured firewall mark and policy-routing exception. SnarkyCtl verifies these NordVPN settings but does not change them.

Test this from two independent management paths before relying on it:

1. Keep a Linode Lish console open as a recovery path.
2. Keep one SSH session open through WireGuard.
3. Run `nordvpn disconnect`.
4. Confirm a new SSH connection to `10.8.0.1` still succeeds.
5. Confirm Internet access through the Windows WireGuard client is blocked.
6. Run `nordvpn connect` and confirm Internet access returns through a NordVPN exit IP.

If WireGuard management stops working, use Lish to run `nordvpn set killswitch off`, restore access, and inspect the mark, routing policy, and allowlist before trying again.

---

# 5. Configure WireGuard on VPS

Generate server keys:

```bash
umask 077
wg genkey | tee server.key | wg pubkey > server.pub
```

Create:

```bash
nano /etc/wireguard/wg0.conf
```

Example:

```ini
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = SERVER_PRIVATE_KEY
FwMark = 0xe1f1

# Forwarding and NAT are managed transactionally by
# scripts/snarkypuss-activate.py, not by wg-quick hooks.

[Peer]
PublicKey = CLIENT_PUBLIC_KEY
AllowedIPs = 10.8.0.2/32
PersistentKeepalive = 25
```

The FwMark is essential. It causes WireGuard transport packets to bypass NordVPN's policy routing. Without it, NordVPN attempts to send WireGuard's own UDP packets through the VPN, preventing tunnel establishment.

Enable IP forwarding:

```bash
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p
```

Enable service:

```bash
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
```

Verify:

```bash
wg show
```

---

# 6. Configure Windows WireGuard Client

Install WireGuard:

https://www.wireguard.com/install/

Generate client keys.

Create tunnel:

```ini
[Interface]
PrivateKey = CLIENT_PRIVATE_KEY
Address = 10.8.0.2/24
DNS = 10.8.0.1

[Peer]
PublicKey = SERVER_PUBLIC_KEY
Endpoint = VPS_PUBLIC_IP:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Import tunnel.

Activate.

Install as service:

```powershell
& "C:\Program Files\WireGuard\wireguard.exe" `
    /installtunnelservice `
    "C:\Program Files\WireGuard\Data\Configurations\snarkypuss.conf.dpapi"
```

Verify:

```powershell
Get-Service *WireGuard*
```

Expected:

```text
WireGuard
WireGuardTunnel$snarkypuss
```

---

# 7. Configure DNS

Edit:

```bash
nano /etc/dnsmasq.conf
```

Recommended:

```text
interface=wg0
listen-address=10.8.0.1
bind-interfaces

server=1.1.1.1
server=1.0.0.1

cache-size=1000
```

Restart:

```bash
systemctl restart dnsmasq
systemctl enable dnsmasq
```

Verify:

```bash
ss -lun | grep ':53'
```

Test:

```bash
dig @10.8.0.1 example.com
```

---

# 8. Configure Forwarding and NAT

The supported method is the transactional activation workflow near the top of this document.
Do not flush the built-in `POSTROUTING` chain: it may contain provider or administrator
rules unrelated to Snarkypuss.

The activation script creates dedicated chains and inserts one jump into each parent chain.
Inspect them with:

```bash
iptables -S SNARKYPUSS_FORWARD
iptables -t nat -S SNARKYPUSS_NAT
iptables -S FORWARD
iptables -t nat -S POSTROUTING
```

The forwarding chain accepts established return traffic and client traffic arriving from the
private WireGuard interface. The NAT chain masquerades the private client network without
choosing a route. The configured VPN provider remains responsible for routing, its kill
switch, Locked mode, and an explicitly requested Direct VPS mode.

Use the activation token and rollback script rather than manually deleting these chains.

---

# 9. Configure Linode Cloud Firewall

Recommended inbound rules:

| Protocol | Port  | Source    |
| -------- | ----- | --------- |
| UDP      | 51820 | 0.0.0.0/0 |

Do NOT expose:

```text
TCP/22
```

Administrative access should occur only over WireGuard or LIST shell.

---

# 10. Configure SSH

Generate keys on Windows:

```powershell
ssh-keygen -t ed25519
```

Copy:

```powershell
ssh-copy-id root@10.8.0.1
```

Test:

```powershell
ssh root@10.8.0.1
```

Optional hosts entry:

File:

```text
C:\Windows\System32\drivers\etc\hosts
```

Add:

```text
10.8.0.1 snarkypuss
```

Then:

```powershell
ssh root@snarkypuss
```

---

# 11. Verify Operation

Connect NordVPN:

```bash
nordvpn connect
```

Check:

```bash
nordvpn status
wg show
```

From Windows:

```powershell
ping 10.8.0.1
tracert 8.8.8.8
```

Expected:

```text
Hop 1: WireGuard tunnel
Final IP: NordVPN exit node
```

Check public IP:

```powershell
curl ifconfig.me
```

Should display:

```text
NordVPN IP
```

---

# 12. DNS Leak Testing

Visit:

```text
https://ipleak.net
https://dnsleaktest.com
```

Expected:

* No ISP DNS servers.
* No home IP.
* DNS requests appear from NordVPN.

---

# 13. Useful Diagnostics

Show routes:

```bash
ip route
ip rule
```

WireGuard:

```bash
wg show
```

NordVPN:

```bash
nordvpn status
```

Packet capture:

```bash
tcpdump -ni wg0
tcpdump -ni nordlynx
```

Firewall:

```bash
iptables -L -n -v
iptables -t nat -L -n -v
```

DNS:

```bash
dig @10.8.0.1 example.com
```

---

# 14. Backup Checklist

Back up:

```text
/etc/wireguard/
/etc/dnsmasq.conf
/etc/iptables/rules.v4
/root/.ssh/
README.md
SETUP.md
```

Create a Linode image after successful deployment.

---

# Final Architecture

```text
Home PC
    ↓
WireGuard
    ↓
snarkypuss VPS (Texas)
    ↓
NordVPN
    ↓
Internet
```

The VPS no longer depends on the client's changing public IP address.

Only UDP port 51820 must remain publicly accessible.