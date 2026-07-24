#!/bin/sh

set -u

tunnel_interface=wg0
client_cidr=10.8.0.0/24
listen_port=51820
dns_service=dnsmasq
failures=0
warnings=0

usage() {
    cat <<'EOF'
Usage: snarkypuss-preflight.sh [OPTIONS]

Read-only readiness checks for a Snarkypuss VPN gateway host.

Options:
  --tunnel-interface NAME  Private tunnel interface (default: wg0)
  --client-cidr CIDR       Private client network (default: 10.8.0.0/24)
  --listen-port PORT       Private tunnel UDP port (default: 51820)
  --dns-service NAME       DNS systemd service (default: dnsmasq)
  -h, --help               Show this help

Exit status:
  0  Checks completed without a blocking failure; warnings may be present
  1  One or more blocking readiness checks failed
  2  Invalid command-line usage

This script does not install packages, write files, change firewall rules, alter
routes, start services, or enable IP forwarding.
EOF
}

pass() {
    printf 'PASS: %s\n' "$1"
}

info() {
    printf 'INFO: %s\n' "$1"
}

warn() {
    warnings=$((warnings + 1))
    printf 'WARN: %s\n' "$1"
}

fail() {
    failures=$((failures + 1))
    printf 'FAIL: %s\n' "$1"
}

need_value() {
    if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        printf 'Missing value for %s\n' "$1" >&2
        usage >&2
        exit 2
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tunnel-interface)
            need_value "$@"
            tunnel_interface=$2
            shift 2
            ;;
        --client-cidr)
            need_value "$@"
            client_cidr=$2
            shift 2
            ;;
        --listen-port)
            need_value "$@"
            listen_port=$2
            shift 2
            ;;
        --dns-service)
            need_value "$@"
            dns_service=$2
            shift 2
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

case "$tunnel_interface" in
    ""|*[!A-Za-z0-9_.-]*)
        printf 'Invalid tunnel interface name: %s\n' "$tunnel_interface" >&2
        exit 2
        ;;
esac

if [ "${#tunnel_interface}" -gt 15 ]; then
    printf 'Tunnel interface names may not exceed 15 characters: %s\n' \
        "$tunnel_interface" >&2
    exit 2
fi

case "$client_cidr" in
    */*) ;;
    *)
        printf 'Client network must be expressed as CIDR: %s\n' "$client_cidr" >&2
        exit 2
        ;;
esac

case "$listen_port" in
    ""|*[!0-9]*)
        printf 'Invalid UDP listen port: %s\n' "$listen_port" >&2
        exit 2
        ;;
esac
if [ "$listen_port" -lt 1 ] || [ "$listen_port" -gt 65535 ]; then
    printf 'UDP listen port must be between 1 and 65535: %s\n' "$listen_port" >&2
    exit 2
fi

printf '%s\n' "Snarkypuss gateway preflight (read-only)"
printf 'Tunnel interface: %s\nClient network: %s\nListen port: %s/udp\n\n' \
    "$tunnel_interface" "$client_cidr" "$listen_port"

if [ -r /etc/os-release ]; then
    # The file is supplied by the operating system and contains shell assignments.
    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ]; then
        pass "Ubuntu 24.04 detected."
    else
        warn "Reference platform is Ubuntu 24.04; detected ${PRETTY_NAME:-unknown Linux}."
    fi
else
    warn "Cannot read /etc/os-release."
fi

if [ "$(id -u)" -eq 0 ]; then
    pass "Running as root; all read-only system checks should be visible."
else
    warn "Not running as root; some firewall and service checks may be incomplete."
fi

for command in ip sysctl systemctl ss; do
    if command -v "$command" >/dev/null 2>&1; then
        pass "Required command is available: $command"
    else
        fail "Required command is missing: $command"
    fi
done

for command in wg dnsmasq iptables iptables-save iptables-restore \
    netfilter-persistent systemd-run curl; do
    if command -v "$command" >/dev/null 2>&1; then
        pass "Gateway command is available: $command"
    else
        warn "Gateway command is not installed yet: $command"
    fi
done

if [ -d /run/systemd/system ]; then
    pass "systemd is running."
else
    fail "systemd does not appear to be running."
fi

if command -v ip >/dev/null 2>&1; then
    if ip route show default 2>/dev/null | grep -q .; then
        pass "A default IPv4 route is present."
        info "Default route: $(ip route show default 2>/dev/null | head -n 1)"
    else
        fail "No default IPv4 route is present."
    fi

    if ip link show dev "$tunnel_interface" >/dev/null 2>&1; then
        warn "Interface $tunnel_interface already exists; inspect it before reconfiguration."
    else
        pass "Interface name $tunnel_interface is currently available."
    fi
fi

if command -v sysctl >/dev/null 2>&1; then
    forwarding=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || printf unknown)
    case "$forwarding" in
        0) info "IPv4 forwarding is currently disabled; configuration will need to enable it." ;;
        1) pass "IPv4 forwarding is already enabled." ;;
        *) warn "Could not determine net.ipv4.ip_forward." ;;
    esac
fi

if command -v ss >/dev/null 2>&1; then
    if ss -H -lun 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$listen_port$"; then
        warn "UDP port $listen_port is already bound; verify that the owning service is expected."
    else
        pass "UDP port $listen_port does not appear to be bound."
    fi
fi

if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet ssh.service 2>/dev/null \
        || systemctl is-active --quiet sshd.service 2>/dev/null; then
        pass "An SSH service is active."
    else
        warn "No active ssh.service or sshd.service was detected."
    fi

    if systemctl cat "$dns_service.service" >/dev/null 2>&1; then
        info "DNS service unit exists: $dns_service.service"
    else
        warn "DNS service unit is not installed: $dns_service.service"
    fi
fi

if [ -d /etc/wireguard ]; then
    info "/etc/wireguard already exists."
else
    info "/etc/wireguard does not exist yet."
fi

warn "Confirm working VPS console access before applying future network or firewall changes."

printf '\nPreflight summary: %s failure(s), %s warning(s).\n' "$failures" "$warnings"
if [ "$failures" -gt 0 ]; then
    exit 1
fi
exit 0
