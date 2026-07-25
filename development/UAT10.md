# Plan 10 User-Acceptance Record

## Result

**Accepted for `0.10.0.dev4`.**

The project owner completed the catalogue transition, exercised the provider-neutral
dashboard editor, added destinations, and confirmed that the resulting configuration and
UI operate correctly.

The accepted production model is:

- SQLite is the only documented target backend.
- `/var/lib/snarkyctl/targets.db` is persistent root-owned application data.
- The privileged daemon is the only production database reader and writer.
- Destinations are managed through the authenticated dashboard or administrative CLI.
- Ordinary target and status APIs expose aliases and labels, never selector documents.
- Package installation and upgrade never initialize, replace, migrate, or delete the
  database automatically.

## Release checks

The `0.10.0.dev4` release candidate must pass:

- Complete automated Python tests and the coverage threshold.
- Static type checking.
- Dashboard JavaScript syntax validation.
- Wheel build.
- Debian binary-package build.
- Package-content inspection confirming that no target catalogue is shipped.
- Upgrade-behavior inspection confirming that `targets.db` is not a package-owned file.

## Operational checks

The accepted operational procedure remains:

1. Initialize the empty SQLite database explicitly on a new installation.
2. Add the first destination through **Manage VPN destinations**.
3. Verify add, edit, reorder, remove, and revision-conflict behavior.
4. Confirm connection by alias.
5. Confirm persistence after service restart and reboot.
6. Create and verify a consistent database backup.
7. Confirm the `snarkyctl` account cannot read the database.
8. Confirm ordinary API responses contain no selector documents.

Live VPN behavior, reboot persistence, and provider-specific network safety remain
deployment checks because they require the actual VPS and VPN provider.
