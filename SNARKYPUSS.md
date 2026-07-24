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

The setup file contains the interface name, server and client tunnel addresses, UDP listen
port, DNS upstream IP addresses, and the path to a file containing the **client's public
WireGuard key**. It must never contain either the client or server private key.

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
| `/etc/sysctl.d/90-snarkypuss.conf` | `0644` | Persistent IPv4-forwarding setting |

The exact WireGuard filenames follow `tunnel_interface`. The private-key directory is mode
`0700`. Repeated application preserves the existing server key and leaves identical files
unchanged. Before replacing a changed file, the generator creates a timestamped
`.bak.YYYYMMDDTHHMMSSZ` copy in the same directory.

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

PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -o wg0 -j ACCEPT

PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -o wg0 -j ACCEPT

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

# 8. Configure NAT

Flush old rules:

```bash
iptables -t nat -F POSTROUTING
```

Create:

```bash
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -j RETURN
iptables -t nat -A POSTROUTING -o nordlynx -j MASQUERADE
```

Persist:

```bash
netfilter-persistent save
```

Verify:

```bash
iptables -t nat -L -n -v
```

Expected:

```text
RETURN      all  --  10.8.0.0/24
MASQUERADE  all  --  out nordlynx
```

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