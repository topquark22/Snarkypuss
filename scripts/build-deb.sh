#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

for command in dpkg-buildpackage dh dh_virtualenv; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '%s\n' "Missing Debian build command: $command" >&2
        printf '%s\n' \
            "Install the packages listed under 'Build the Debian package' in INSTALL.md." >&2
        exit 2
    fi
done

python_version=$(
    python3 -c \
        'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
)
debian_version=$(dpkg-parsechangelog -S Version)
expected_debian_version=$(printf '%s' "$python_version" | sed 's/\.dev/~dev/')-1

if [ "$debian_version" != "$expected_debian_version" ]; then
    printf '%s\n' \
        "Version mismatch: pyproject.toml $python_version expects Debian $expected_debian_version," \
        "but debian/changelog contains $debian_version." >&2
    exit 2
fi

dpkg-buildpackage --build=binary --no-sign
