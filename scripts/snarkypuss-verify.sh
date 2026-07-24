#!/bin/sh

set -u

tunnel_interface=wg0
client_cidr=10.8.0.0/24
dns_service=dnsmasq
public_ip_url=https://api.ipify.org
vps_public_ip=
failures=0
warnings=0

usage() {
    cat <<'EOF'
Usage: snarkypuss-verify.sh [OPTIONS]

Read-only verification of an existing Snarkypuss VPN gateway.

Options:
  --tunnel-interface NAME  Private tunnel interface (default: wg0)
  --client-cidr CIDR       Private client network (default: 10.8.0.0/24)
  --dns-service NAME       DNS systemd service (default: dnsmasq)
  --public-ip-url URL      HTTPS endpoint returning only the caller's IP
                           (default: https://api.ipify.org)
  --vps-public-ip ADDRESS  Known real public IP used to identify direct egress
  -h, --help               Show this help

Exit status:
  0  No structural gateway check failed; warnings may be present
  1  One or more structural gateway checks failed
  2  Invalid command-line usage

This script makes no system changes. Its public-IP request observes egress from
the VPS itself; complete end-to-end verification must also be run from a client
connected through the private tunnel.
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
        --dns-service)
            need_value "$@"
            dns_service=$2
            shift 2
            ;;
        --public-ip-url)
            need_value "$@"
            public_ip_url=$2
            shift 2
            ;;
        --vps-public-ip)
            need_value "$@"
            vps_public_ip=$2
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
case "$public_ip_url" in
    https://*) ;;
    *)
        printf 'Public-IP endpoint must use HTTPS: %s\n' "$public_ip_url" >&2
        exit 2
        ;;
esac

printf '%s\n' "Snarkypuss gateway verification (read-only)"
printf 'Tunnel interface: %s\nClient network: %s\n\n' \
    "$tunnel_interface" "$client_cidr"

if [ "$(id -u)" -ne 0 ]; then
    warn "Not running as root; firewall and WireGuard details may be incomplete."
fi

for command in ip sysctl systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "Required verification command is missing: $command"
    fi
done

if command -v ip >/dev/null 2>&1; then
    if ip link show dev "$tunnel_interface" >/dev/null 2>&1; then
        pass "Tunnel interface exists: $tunnel_interface"
        if ip link show dev "$tunnel_interface" 2>/dev/null \
            | head -n 1 | grep -Eq '<[^>]*UP([,>])'; then
            pass "Tunnel interface has the UP flag."
        else
            warn "Tunnel interface does not have the UP flag."
        fi
        addresses=$(ip -o -4 address show dev "$tunnel_interface" 2>/dev/null || true)
        if [ -n "$addresses" ]; then
            pass "Tunnel interface has an IPv4 address."
            info "Tunnel address: $(printf '%s\n' "$addresses" | head -n 1)"
        else
            fail "Tunnel interface has no IPv4 address."
        fi
    else
        fail "Tunnel interface does not exist: $tunnel_interface"
    fi

    if ip route show default 2>/dev/null | grep -q .; then
        pass "A default IPv4 route is present."
        info "Default route: $(ip route show default 2>/dev/null | head -n 1)"
    else
        fail "No default IPv4 route is present."
    fi
fi

if command -v sysctl >/dev/null 2>&1; then
    forwarding=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || printf unknown)
    if [ "$forwarding" = 1 ]; then
        pass "IPv4 forwarding is enabled."
    else
        fail "IPv4 forwarding is not enabled (observed: $forwarding)."
    fi
fi

if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet "wg-quick@$tunnel_interface.service" 2>/dev/null; then
        pass "wg-quick@$tunnel_interface.service is active."
    else
        warn "wg-quick@$tunnel_interface.service is not active."
    fi
    if systemctl is-active --quiet "$dns_service.service" 2>/dev/null; then
        pass "$dns_service.service is active."
    else
        fail "$dns_service.service is not active."
    fi
fi

if command -v wg >/dev/null 2>&1; then
    if wg show "$tunnel_interface" >/dev/null 2>&1; then
        pass "WireGuard recognizes $tunnel_interface."
        latest_handshake=$(
            wg show "$tunnel_interface" latest-handshakes 2>/dev/null \
                | awk '$2 > latest { latest=$2 } END { print latest+0 }'
        )
        if [ "$latest_handshake" -gt 0 ]; then
            pass "At least one peer has completed a WireGuard handshake."
        else
            warn "No completed WireGuard peer handshake was observed."
        fi
    else
        fail "WireGuard does not recognize $tunnel_interface."
    fi
else
    fail "WireGuard command is missing: wg"
fi

firewall_observed=false
if command -v iptables >/dev/null 2>&1; then
    forward_rules=$(iptables -S FORWARD 2>/dev/null || true)
    nat_rules=$(iptables -t nat -S POSTROUTING 2>/dev/null || true)
    if printf '%s\n' "$forward_rules" | grep -Fq "$tunnel_interface"; then
        pass "Firewall forwarding rules reference $tunnel_interface."
        firewall_observed=true
    else
        warn "No iptables forwarding rule referencing $tunnel_interface was found."
    fi
    if printf '%s\n' "$nat_rules" | grep -Fq "$client_cidr"; then
        pass "NAT rules reference client network $client_cidr."
        firewall_observed=true
    else
        warn "No iptables NAT rule referencing $client_cidr was found."
    fi
fi

if command -v nft >/dev/null 2>&1; then
    nft_rules=$(nft list ruleset 2>/dev/null || true)
    if printf '%s\n' "$nft_rules" | grep -Fq "$tunnel_interface"; then
        pass "nftables rules reference $tunnel_interface."
        firewall_observed=true
    fi
fi

if [ "$firewall_observed" = false ]; then
    warn "Could not confirm gateway forwarding or NAT policy; inspect firewall rules manually."
fi

if command -v ss >/dev/null 2>&1; then
    if ss -H -lun 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)53$'; then
        pass "A UDP DNS listener is present on port 53."
    else
        warn "No UDP DNS listener was detected on port 53."
    fi
fi

if command -v curl >/dev/null 2>&1; then
    if observed_ip=$(curl --fail --silent --show-error --max-time 20 "$public_ip_url"); then
        case "$observed_ip" in
            *[!0-9A-Fa-f:.]*|"")
                warn "Public-IP endpoint returned an unexpected value."
                ;;
            *)
                pass "The VPS can reach the configured public-IP endpoint over verified HTTPS."
                info "Observed VPS egress IP: $observed_ip"
                if [ -n "$vps_public_ip" ]; then
                    if [ "$observed_ip" = "$vps_public_ip" ]; then
                        warn "Observed egress matches the VPS public IP: Direct VPS exposure."
                    else
                        pass "Observed egress differs from the supplied VPS public IP."
                        info "This is consistent with upstream VPN egress but does not prove the client path."
                    fi
                else
                    info "Supply --vps-public-ip to detect obvious Direct VPS egress."
                fi
                ;;
        esac
    else
        warn "Public-IP lookup failed: egress may be Locked, unavailable, or intercepted."
        warn "Do not bypass TLS verification; inspect the CA trust path if curl reports a certificate error."
    fi
else
    warn "curl is unavailable; public egress was not observed."
fi

printf '\nVerification summary: %s failure(s), %s warning(s).\n' "$failures" "$warnings"
printf '%s\n' \
    "Run an external-IP and DNS-leak test from a connected client before trusting the gateway."
if [ "$failures" -gt 0 ]; then
    exit 1
fi
exit 0
