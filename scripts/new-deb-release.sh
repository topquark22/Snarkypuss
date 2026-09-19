#!/bin/sh

set -eu

usage() {
  printf 'Usage: %s CHANGELOG_ENTRY\n' "$0" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

for command in dch dpkg-parsechangelog python3 sed; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command" >&2
    printf '%s\n' "Install devscripts and the Debian packaging prerequisites." >&2
    exit 2
  fi
done

python_version=$(
  python3 -c \
    'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
)
expected_upstream_version=$(printf '%s' "$python_version" | sed 's/\.dev/~dev/')
current_version=$(dpkg-parsechangelog -S Version)

case "$current_version" in
  "$expected_upstream_version"-*)
    current_revision=${current_version#"$expected_upstream_version"-}
    ;;
  *)
    current_revision=
    ;;
esac

case "$current_revision" in
  ""|*[!0-9]*)
    printf '%s\n' \
      "Version mismatch: pyproject.toml $python_version expects Debian" \
      "$expected_upstream_version-<positive revision>, but debian/changelog contains" \
      "$current_version." >&2
    exit 2
    ;;
esac

if [ "$current_revision" -lt 1 ]; then
  printf '%s\n' \
    "Invalid Debian revision: $current_revision; expected a positive integer." >&2
  exit 2
fi

next_revision=$((current_revision + 1))
next_version="$expected_upstream_version-$next_revision"

DEBCHANGE_RELEASE_HEURISTIC=changelog \
  dch --newversion "$next_version" --distribution unstable "$1"

printf 'Created Debian changelog entry for %s.\n' "$next_version"
