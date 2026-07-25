# Mullvad on Linux

This guide prepares a Linux VPS to use the official Mullvad VPN application. Mullvad remains
responsible for its tunnel, routes, DNS integration, firewall, built-in kill switch, and
Lockdown mode.

> **Current SnarkyCtl status:** In `0.11.0.dev0`, the Mullvad adapter is read-only and is not
> registered as an active provider. Do not change `upstream_vpn.provider` to `mullvad` yet.
> The commands below install and configure Mullvad independently so it can be tested safely
> before later Plan 11 phases enable control through SnarkyCtl.


## Before changing VPN state

On a remote VPS, confirm that the provider cannot lock you out permanently:

1. Verify independent console access through the VPS provider.
2. Keep that console open while testing.
3. Record the current working NordVPN and Snarkypuss configuration.
4. Confirm that the private management tunnel remains reachable when Mullvad connects,
   disconnects, or blocks public traffic.
5. Do not enable unattended Lockdown mode until that management path has been tested.

Mullvad Lockdown mode deliberately blocks Internet traffic while Mullvad is disconnected. A
misconfigured management bypass can therefore interrupt SSH and the SnarkyCtl dashboard.


## Supported systems

Mullvad currently supports Ubuntu 24.04 or later and Debian 12 or later. The official
repository also supports other Debian-based distributions that use systemd.

These instructions use the stable Mullvad repository on Ubuntu or Debian. For Fedora and
other installation methods, follow Mullvad's
[official Linux installation guide](https://mullvad.net/en/help/install-mullvad-app-linux).


## Install from the Mullvad repository

Install `curl` from the distribution package repository:

```bash
sudo apt-get update
sudo apt-get install curl
```

Install Mullvad's repository signing key:

```bash
sudo curl -fsSLo /usr/share/keyrings/mullvad-keyring.asc \
  https://repository.mullvad.net/deb/mullvad-keyring.asc
```

Add the stable repository:

```bash
echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc arch=$(dpkg --print-architecture)] https://repository.mullvad.net/deb/stable stable main" \
  | sudo tee /etc/apt/sources.list.d/mullvad.list
```

Install the official package:

```bash
sudo apt-get update
sudo apt-get install mullvad-vpn
```

Enable and start the Mullvad daemon on a headless VPS:

```bash
sudo systemctl enable --now mullvad-daemon.service
sudo systemctl status mullvad-daemon.service
```

The second command should report `active (running)`. If it does not, inspect the service
log:

```bash
sudo journalctl -u mullvad-daemon.service -b --no-pager
```


## Verify the CLI and daemon

Check the installed client and daemon versions:

```bash
sudo mullvad version
```

The output should identify the current version and report that it is supported. Then inspect
the current connection state:

```bash
sudo mullvad status
sudo mullvad status --json
```

SnarkyCtl's read-only adapter uses the JSON form. It does not parse the localized
human-readable status display.


## Log in manually

SnarkyCtl does not store or submit a Mullvad account number. Log in directly with the
Mullvad CLI:

```bash
sudo mullvad account login
```

The command prompts for the account number instead of placing it in shell history.

Verify the account state:

```bash
sudo mullvad account get
```

Be careful when copying this output into tickets or logs because it can display the Mullvad
account number and device information.


## Basic manual connection test

Select a relay country using its two-letter Mullvad country code, then connect:

```bash
sudo mullvad relay set location se
sudo mullvad connect
sudo mullvad status
```

To use a city, provide the country and city codes:

```bash
sudo mullvad relay set location se got
```

A specific server may also be selected:

```bash
sudo mullvad relay set location se got se-got-wg-001
```

Replace these examples with an appropriate Mullvad location. The official
[Mullvad CLI guide](https://mullvad.net/en/help/cli-command-wg) describes the currently
supported country, city, server, and connection commands.

Disconnect manually with:

```bash
sudo mullvad disconnect
sudo mullvad status
```

At the present Plan 11 phase, these are administrator-run tests. SnarkyCtl does not execute
the connect, relay-selection, or disconnect commands.


## Lockdown mode

Mullvad has a built-in kill switch while a VPN connection is being established or has failed.
Its optional **Lockdown mode** goes further: it continues blocking Internet access after an
intentional disconnect.

Inspect the setting:

```bash
sudo mullvad lockdown-mode get
```

Enable it only after confirming console and private-management access:

```bash
sudo mullvad lockdown-mode set on
sudo mullvad lockdown-mode get
```

With Lockdown mode enabled, this test should leave public Internet access blocked:

```bash
sudo mullvad disconnect
sudo mullvad status
```

Confirm that the private management tunnel and VPS console remain available. Then reconnect:

```bash
sudo mullvad connect
sudo mullvad status
```

To deliberately allow direct public VPS egress during manual testing:

```bash
sudo mullvad lockdown-mode set off
sudo mullvad disconnect
sudo mullvad lockdown-mode get
sudo mullvad status
```

This exposes the VPS's real public IP. Do not treat provider failure as permission to enter
this state.

SnarkyCtl `0.11.0.dev0` can parse Lockdown status through its read-only adapter, but it
cannot change the setting.


## Auto-connect and reboot behavior

Inspect Mullvad's auto-connect setting:

```bash
sudo mullvad auto-connect get
```

After management-path testing, enable connection during daemon startup:

```bash
sudo mullvad auto-connect set on
sudo mullvad auto-connect get
```

Perform a controlled reboot test with the VPS console available:

```bash
sudo reboot
```

After the host returns, verify:

```bash
sudo systemctl status mullvad-daemon.service
sudo mullvad status
sudo mullvad lockdown-mode get
sudo mullvad auto-connect get
```

Also verify SSH, the private management tunnel, DNS, and the SnarkyCtl dashboard.


## SnarkyCtl provider configuration

Phase 1 introduced a bounded Mullvad configuration model:

```yaml
upstream_vpn:
  provider: nordvpn
  providers:
    mullvad:
      executable: /usr/bin/mullvad
      service: mullvad-daemon.service
      expected_interfaces: []
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
```

This block may describe an inactive Mullvad installation, but the active provider must remain
`nordvpn` during Phase 2. Mullvad is intentionally absent from the trusted provider
registry.

Do not guess an expected interface name. A tested interface expectation will be documented
before Mullvad is registered for production use.


## Troubleshooting

If the CLI reports a management-interface error, verify the daemon:

```bash
sudo systemctl status mullvad-daemon.service
sudo journalctl -u mullvad-daemon.service -b --no-pager
```

If necessary, restart it:

```bash
sudo systemctl restart mullvad-daemon.service
sudo mullvad status
```

If DNS stops resolving after provider transitions, inspect:

```bash
cat /etc/resolv.conf
resolvectl status
sudo grep -i dns /var/log/mullvad-vpn/daemon.log
```

Do not disable certificate checking, flush firewall tables, or add guessed routes as a
troubleshooting shortcut. Mullvad owns its routing, DNS, and firewall integration.


## Remove Mullvad

Removing SnarkyCtl never removes Mullvad. To remove the Mullvad package separately:

```bash
sudo apt-get purge mullvad-vpn
```

Remove its apt source only if it is no longer wanted:

```bash
sudo rm /etc/apt/sources.list.d/mullvad.list
sudo apt-get update
```


## Upstream references

- [Install Mullvad on Linux](https://mullvad.net/en/help/install-mullvad-app-linux)
- [Mullvad CLI commands](https://mullvad.net/en/help/cli-command-wg)
- [Using the Mullvad VPN app](https://mullvad.net/en/help/using-mullvad-vpn-app)
