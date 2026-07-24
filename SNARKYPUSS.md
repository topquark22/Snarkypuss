# Snarkypuss Private VPN Gateway: Technical Reference

## Purpose and scope

This is the technical implementation reference for the **Snarkypuss** private VPN gateway.
For the project overview, safety model, and the relationship between Snarkypuss and its
SnarkyCtl management utility, begin with [README.md](README.md).

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