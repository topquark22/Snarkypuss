#!/bin/sh

set -eu

dry_run=false
skip_update=false
allow_unsupported=false

usage() {
    cat <<'EOF'
Usage: sudo scripts/snarkypuss-install.sh [OPTIONS]

Install the operating-system packages used by the base Snarkypuss gateway.

Options:
  --dry-run            Print the apt-get commands without changing the system
  --skip-update        Do not run apt-get update before installation
  --allow-unsupported  Permit a Linux release other than Ubuntu 24.04
  -h, --help           Show this help

This script installs only provider-neutral gateway dependencies. It installs
`dnsmasq-base` for the dnsmasq executable but does not install or configure the
Ubuntu dnsmasq system service. It does not install or configure NordVPN or
another upstream VPN provider, write gateway configuration, explicitly activate
gateway services, change routes, or alter firewall rules.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            dry_run=true
            shift
            ;;
        --skip-update)
            skip_update=true
            shift
            ;;
        --allow-unsupported)
            allow_unsupported=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ ! -r /etc/os-release ]; then
    printf '%s\n' "Cannot read /etc/os-release." >&2
    exit 1
fi

# The file is supplied by the operating system and contains shell assignments.
# shellcheck disable=SC1091
. /etc/os-release
if { [ "${ID:-}" != ubuntu ] || [ "${VERSION_ID:-}" != 24.04 ]; } \
    && [ "$allow_unsupported" != true ]; then
    printf '%s\n' \
        "The supported platform is Ubuntu 24.04; detected ${PRETTY_NAME:-unknown Linux}." \
        "Review the package names, then use --allow-unsupported if appropriate." >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' "Required command is unavailable: apt-get" >&2
    exit 1
fi

if [ "$dry_run" != true ] && [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "Run this script as root, for example with sudo." >&2
    exit 1
fi

packages="
ca-certificates
curl
dnsmasq-base
dnsutils
iproute2
iptables
iptables-persistent
net-tools
nftables
python3
tcpdump
traceroute
vim
wireguard
wireguard-tools
"

print_install_command() {
    printf '%s' "DEBIAN_FRONTEND=noninteractive apt-get install --yes"
    for package in $packages; do
        printf ' %s' "$package"
    done
    printf '\n'
}

if [ "$dry_run" = true ]; then
    printf '%s\n' "Snarkypuss package installation dry run"
    if [ "$skip_update" != true ]; then
        printf '%s\n' "apt-get update"
    fi
    print_install_command
    printf '%s\n' \
        "Snarkypuss uses dnsmasq-base and a dedicated snarkypuss-dns.service; the stock dnsmasq service/configuration is not installed or modified." \
        "No packages were installed and no services or network settings were changed."
    exit 0
fi

if [ "$skip_update" != true ]; then
    apt-get update
fi

# Deliberately avoid shell expansion of user-provided values. The package list
# is fixed in this reviewed script.
# shellcheck disable=SC2086
DEBIAN_FRONTEND=noninteractive apt-get install --yes $packages

printf '%s\n' \
    "Base Snarkypuss gateway packages are installed." \
    "The stock dnsmasq service/configuration was not installed or modified." \
    "No Snarkypuss service, route, or firewall rule was activated."
