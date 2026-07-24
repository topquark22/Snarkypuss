#!/bin/sh

set -eu

usage() {
    printf 'Usage: sudo %s PATH_TO_SNARKYCTL_DEB\n' "$0" >&2
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "Run this script as root, for example with sudo." >&2
    exit 2
fi

for command in apt-get dpkg-deb systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command is unavailable: %s\n' "$command" >&2
        exit 2
    fi
done

package_path=$1
if [ ! -f "$package_path" ]; then
    printf 'Package does not exist or is not a regular file: %s\n' "$package_path" >&2
    exit 2
fi

package_name=$(dpkg-deb --field "$package_path" Package)
if [ "$package_name" != "snarkyctl" ]; then
    printf 'Refusing to install package %s from %s\n' "$package_name" "$package_path" >&2
    exit 2
fi

package_directory=$(CDPATH= cd -- "$(dirname -- "$package_path")" && pwd)
package_path=$package_directory/$(basename -- "$package_path")

completed=false
cleanup() {
    if [ "$completed" != true ]; then
        printf '%s\n' \
            "Reinstallation did not complete. SnarkyCtl services may remain stopped." \
            "Inspect the error above before starting them manually." >&2
    fi
}
trap cleanup EXIT HUP INT TERM

printf '%s\n' "Stopping SnarkyCtl services..."
systemctl stop snarkyctl-web.service
systemctl stop snarkyctl-control.service
systemctl stop snarkyctl-control.socket

printf 'Reinstalling %s...\n' "$package_path"
apt-get install --yes --reinstall "$package_path"

printf '%s\n' "Reloading systemd and starting SnarkyCtl..."
systemctl daemon-reload
systemctl start snarkyctl-control.socket
systemctl start snarkyctl-control.service
systemctl start snarkyctl-web.service

systemctl is-active --quiet snarkyctl-control.socket
systemctl is-active --quiet snarkyctl-control.service
systemctl is-active --quiet snarkyctl-web.service

completed=true
trap - EXIT HUP INT TERM

printf '%s\n' "SnarkyCtl was reinstalled and restarted successfully."
systemctl --no-pager --full status \
    snarkyctl-control.socket \
    snarkyctl-control.service \
    snarkyctl-web.service
