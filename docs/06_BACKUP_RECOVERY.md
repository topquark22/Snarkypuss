# Snarkypuss Backup and Recovery Guide

## Purpose

This guide explains how to back up a working Snarkypuss installation and how to recover it
when configuration, services, or the entire Linode are lost.

For diagnosis of a running but broken system, use
[05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) first. This document is for preservation,
restoration, migration, and disaster recovery.

## 1. Understand the three recovery levels

Choose the least disruptive recovery method that matches the failure.

| Situation | Preferred recovery method |
|---|---|
| One configuration file or service is broken | Restore the affected file, then validate and restart only the affected service. |
| The Linode operating system is badly damaged | Restore a known-good Linode snapshot, then verify Snarkypuss from Windows. |
| The Linode is lost, deleted, or being replaced | Create a fresh Ubuntu 24.04 Linode and restore the saved Snarkypuss configuration and secrets. |

A backup is useful only if it exists somewhere other than the system it protects. Do not
keep the only copy of the recovery material on the Snarkypuss Linode itself.

## 2. What must be backed up

A complete portable recovery set should contain the following files when they exist.

### WireGuard and base networking

```text
/etc/snarkypuss-setup.conf
/etc/wireguard/wg0.conf
/etc/wireguard/wg0.private.key
/etc/snarkypuss/dnsmasq.conf
/etc/systemd/system/snarkypuss-dns.service
/etc/sysctl.d/90-snarkypuss.conf
/etc/iptables/rules.v4
```

The most important identity file in this group is:

```text
/etc/wireguard/wg0.private.key
```

Preserving that key allows a rebuilt Linode to retain the same WireGuard server identity.
If you generate a new server key instead, the Windows WireGuard tunnel must be updated with
the new server public key.

Older installations may still contain the former Snarkypuss dnsmasq files:

```text
/etc/dnsmasq.d/snarkypuss.conf
/etc/systemd/system/dnsmasq.service.d/snarkypuss.conf
```

Preserve them in a pre-migration backup if the system has not yet completed the dedicated
DNS-service cutover. They are not part of the active configuration after a successful
migration to `snarkypuss-dns.service`.

### SnarkyCtl

```text
/etc/snarkyctl/snarkyctl.yaml
/etc/snarkyctl/auth.htpasswd
/etc/snarkyctl/tls/server.crt
/etc/snarkyctl/tls/server.key
/etc/snarkyctl/tls/ca.crt
/var/lib/snarkyctl/targets.db
```

If your private certificate-authority key is stored separately from the Linode, keep that
CA private key in its own secure backup as well. It should not be copied onto the Linode merely
for convenience.

### Useful records that are not files on the Linode

Keep a secure note of:

- the Linode region and plan,
- the Linode public IPv4 address,
- the private WireGuard network (`10.8.0.0/24` in the reference deployment),
- the WireGuard UDP port (`51820/UDP` in the reference deployment),
- the Linode Firewall rules,
- the Windows hosts-file entry `10.8.0.1 snarkypuss`, and
- the NordVPN account information needed to obtain a fresh access token.

Do not store a NordVPN access token in the Git repository or in ordinary documentation.

## 3. Protect the backup material

The recovery set contains credentials and private keys. Treat it as sensitive data.

In particular, these files must never be committed to Git or shared publicly:

```text
/etc/wireguard/wg0.private.key
/etc/snarkyctl/auth.htpasswd
/etc/snarkyctl/tls/server.key
```

The target database may also reveal the destinations you configured. The main SnarkyCtl
configuration can contain deployment-specific information even when it contains no password.

Store the portable backup in an encrypted location that is independent of the Linode. A
password-protected or otherwise encrypted local archive plus a second independent copy is a
reasonable minimum for a personal installation.

A Linode snapshot is useful, but do not make it your only backup. A snapshot lives with the
same hosting account as the VPS it protects.

## 4. Take a Linode snapshot before major changes

Before a major package upgrade, networking redesign, firewall change, or migration, create a
Linode snapshot in Akamai Cloud Manager.

The snapshot is the fastest way to return the complete machine to a known state because it
captures the operating system and the Snarkypuss files together.

Before taking the snapshot:

1. Confirm that the system is in a known state.
2. Confirm that WireGuard works from Windows.
3. Confirm that DNS works.
4. Confirm that NordVPN is either Protected VPN or deliberately Locked.
5. Confirm that the SnarkyCtl dashboard is reachable.
6. Record the date and the reason for the snapshot.

A snapshot taken from an already broken system is not a substitute for a known-good snapshot.

## 5. Back up the SnarkyCtl destination database

Do not copy a live SQLite database casually when a supported backup command is available.
Create a consistent backup with:

```bash
sudo snarkyctl targets-db backup --output /root/targets.db.backup
sudo chmod 0600 /root/targets.db.backup
```

Then copy `/root/targets.db.backup` to the secure off-Linode backup location.

After the copy has been verified, the temporary `/root/targets.db.backup` file may be removed
from the Linode.

The active database normally lives at:

```text
/var/lib/snarkyctl/targets.db
```

## 6. Create a portable configuration backup

A simple recovery directory can be assembled as root. The following example copies the
important files without changing the running services:

```bash
sudo install -d -m 0700 /root/snarkypuss-backup
sudo install -d -m 0700 /root/snarkypuss-backup/wireguard
sudo install -d -m 0700 /root/snarkypuss-backup/dnsmasq
sudo install -d -m 0700 /root/snarkypuss-backup/snarkyctl
sudo install -d -m 0700 /root/snarkypuss-backup/system
```

Copy the networking files that exist:

```bash
sudo cp -a /etc/snarkypuss-setup.conf /root/snarkypuss-backup/ 2>/dev/null || true
sudo cp -a /etc/wireguard/wg0.conf /root/snarkypuss-backup/wireguard/
sudo cp -a /etc/wireguard/wg0.private.key /root/snarkypuss-backup/wireguard/
sudo cp -a /etc/snarkypuss/dnsmasq.conf /root/snarkypuss-backup/dnsmasq/
sudo cp -a /etc/systemd/system/snarkypuss-dns.service /root/snarkypuss-backup/system/
sudo cp -a /etc/sysctl.d/90-snarkypuss.conf /root/snarkypuss-backup/system/
sudo cp -a /etc/iptables/rules.v4 /root/snarkypuss-backup/system/ 2>/dev/null || true
```

Copy the SnarkyCtl configuration and credentials:

```bash
sudo cp -a /etc/snarkyctl/snarkyctl.yaml /root/snarkypuss-backup/snarkyctl/
sudo cp -a /etc/snarkyctl/auth.htpasswd /root/snarkypuss-backup/snarkyctl/
sudo cp -a /etc/snarkyctl/tls /root/snarkypuss-backup/snarkyctl/
```

Create the consistent database backup directly inside the recovery directory:

```bash
sudo snarkyctl targets-db backup \
    --output /root/snarkypuss-backup/snarkyctl/targets.db.backup
sudo chmod 0600 /root/snarkypuss-backup/snarkyctl/targets.db.backup
```

Review the directory before moving it off the Linode:

```bash
sudo find /root/snarkypuss-backup -type f -printf '%p\n'
```

Do not leave the portable recovery directory as the only backup. Transfer it securely to an
independent encrypted location.

## 7. Restore one damaged configuration file

When only one component is broken, restore only what is necessary.

For example, after restoring the private DNS configuration, validate exactly that file before
restarting DNS:

```bash
sudo dnsmasq --test --conf-file=/etc/snarkypuss/dnsmasq.conf
sudo systemctl daemon-reload
sudo systemctl restart snarkypuss-dns.service
sudo systemctl status snarkypuss-dns.service --no-pager
```

After restoring WireGuard configuration, verify the file and service before assuming the
private path works:

```bash
sudo systemctl restart wg-quick@wg0.service
sudo wg show wg0
```

After restoring SnarkyCtl configuration, validate it before restarting the web/control path:

```bash
sudo snarkyctl validate-config --config /etc/snarkyctl/snarkyctl.yaml
sudo snarkyctl preflight --config /etc/snarkyctl/snarkyctl.yaml
```

Do not restore several unrelated files at once unless the failure actually requires it. A
small, reversible repair is easier to verify.

## 8. Restore the destination database

Before replacing the active database, stop making destination changes in the dashboard.
Keep LISH available.

Preserve the current database first if it still exists:

```bash
sudo cp -a /var/lib/snarkyctl/targets.db \
    /var/lib/snarkyctl/targets.db.before-restore
```

Copy the known-good backup into place, then restore the ownership and permissions expected by
the installed system. Verify the database afterward:

```bash
sudo snarkyctl targets-db check
sudo snarkyctl targets list
```

If the check reports an ownership, schema, or integrity problem, correct that problem before
using the dashboard to change destinations.

## 9. Restore a Linode snapshot

Use a Linode snapshot when the whole machine needs to return to a known-good state.

After the snapshot restore completes:

1. Open LISH before depending on network access.
2. Confirm the Linode public IPv4 address. If it changed, update the Windows WireGuard
   `Endpoint` value and any applicable Linode Firewall rule assumptions.
3. Check the base services:

   ```bash
   systemctl status wg-quick@wg0.service --no-pager
   systemctl status snarkypuss-dns.service --no-pager
   systemctl status ssh.service --no-pager
   systemctl status snarkyctl-control.socket --no-pager
   systemctl status snarkyctl-web.service --no-pager
   ```

4. Check NordVPN:

   ```bash
   nordvpn settings
   nordvpn status
   ```

5. Reconnect from Windows and repeat the acceptance checks in Sections 11 and 12 below.

Do not assume that a snapshot restore also preserves an external public IP allocation or
provider-session state exactly as it was when the snapshot was taken.

## 10. Rebuild a completely lost Linode

If the original VPS no longer exists, rebuild in a controlled order rather than copying all
files onto an unprepared host.

1. Create a new Ubuntu 24.04 Linode using the procedure in
   [01_SETUP_VPS.md](01_SETUP_VPS.md).
2. Keep LISH open.
3. Install the base Snarkypuss packages.
4. Restore the original WireGuard server private key **before** generating or activating a
   replacement WireGuard identity.
5. Restore the known-good WireGuard, dedicated DNS, sysctl, and persistent firewall
   configuration.
6. Install NordVPN and authenticate it with a current access token.
7. Re-create the required NordVPN settings and management allowlist.
8. Validate WireGuard and DNS before relying on them.
9. Install the SnarkyCtl package.
10. Restore `/etc/snarkyctl/snarkyctl.yaml`, authentication data, and TLS material.
11. Restore the target database and run `snarkyctl targets-db check`.
12. Run SnarkyCtl validation and preflight.
13. Enable/start the documented services.
14. Update the Windows WireGuard `Endpoint` if the new Linode has a different public IPv4
    address.
15. Verify the Linode Firewall.
16. Perform the complete recovery acceptance test below.

If the original `/etc/wireguard/wg0.private.key` is unavailable, generate a new WireGuard
server identity using the normal setup procedure and replace the server public key in the
Windows WireGuard tunnel.

## 11. Verify a restore before trusting it

A restored system is not complete merely because the files exist. From LISH and Windows,
verify each layer in order.

### On the Linode

```bash
systemctl is-active wg-quick@wg0.service
systemctl is-active snarkypuss-dns.service
sudo wg show wg0
sudo dnsmasq --test --conf-file=/etc/snarkypuss/dnsmasq.conf
nordvpn settings
nordvpn status
sudo snarkyctl targets-db check
sudo snarkyctl preflight --config /etc/snarkyctl/snarkyctl.yaml
```

### From Windows

Verify that:

1. the `snarkypuss` WireGuard tunnel establishes a recent handshake,
2. traffic counters increase in both directions,
3. `10.8.0.1` is reachable,
4. DNS resolution succeeds through `10.8.0.1`,
5. Windows has actually registered `10.8.0.1` as the DNS server on the active WireGuard
   interface,
6. `https://snarkypuss:8443/` opens without an unexpected certificate warning,
7. the dashboard reports the expected gateway mode,
8. Protected VPN traffic exits through NordVPN rather than the Linode public IP, and
9. intentionally disconnecting NordVPN with leak protection active blocks forwarded public
   Internet traffic while private management remains reachable.

Do not skip the fail-closed test after a full rebuild or snapshot recovery.

## 12. Reboot after a major recovery

A recovery that works only until the next reboot is incomplete.

After the restored system passes the initial checks, perform a controlled reboot while LISH
remains available. Then verify:

```bash
systemctl is-active wg-quick@wg0.service snarkypuss-dns.service ssh.service
systemctl is-active snarkyctl-control.socket snarkyctl-web.service
```

Reconnect from Windows and repeat the essential WireGuard, DNS, dashboard, provider-state,
and public-IP checks.

## 13. Migration to a new Linode

An intentional migration is similar to disaster recovery, except that the old Linode remains
available for comparison.

Before starting:

- create a current target-database backup,
- create a portable configuration backup,
- take a snapshot of the old Linode,
- record its Linode Firewall rules, and
- keep both LISH consoles available during the change.

Preserve the existing WireGuard server key if you want the Windows peer identity to remain the
same. The new Linode will normally have a different public IPv4 address, so update the
`Endpoint` in the Windows WireGuard application even when the WireGuard keys remain the same.

Do not delete the old Linode until the new one has passed the complete acceptance and reboot
tests.

## 14. Backup checklist

Before a risky change, confirm that you have:

- a recent known-good Linode snapshot,
- a copy of `/etc/wireguard/wg0.private.key`,
- the WireGuard configuration,
- `/etc/snarkypuss/dnsmasq.conf` and `/etc/systemd/system/snarkypuss-dns.service`,
- `/etc/snarkypuss-setup.conf` if used,
- `/etc/iptables/rules.v4` if present,
- the SnarkyCtl configuration,
- `auth.htpasswd`,
- SnarkyCtl TLS files,
- a consistent `targets.db` backup,
- an independent copy of any private CA key,
- a record of the Linode Firewall rules, and
- an encrypted copy of the recovery material stored off the Linode.

The backup is not complete until you can locate it, decrypt it, and identify what date and
system state it represents.
