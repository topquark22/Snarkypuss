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
expected_upstream_version=$(printf '%s' "$python_version" | sed 's/\.dev/~dev/')

case "$debian_version" in
    "$expected_upstream_version"-*)
        debian_revision=${debian_version#"$expected_upstream_version"-}
        ;;
    *)
        debian_revision=
        ;;
esac

case "$debian_revision" in
    ""|*[!0-9]*)
        printf '%s\n' \
            "Version mismatch: pyproject.toml $python_version expects Debian" \
            "$expected_upstream_version-<positive revision>, but debian/changelog contains" \
            "$debian_version." >&2
        exit 2
        ;;
esac

if [ "$debian_revision" -lt 1 ]; then
    printf '%s\n' \
        "Invalid Debian revision: $debian_revision; expected a positive integer." >&2
    exit 2
fi

dpkg-buildpackage --build=binary --no-sign
