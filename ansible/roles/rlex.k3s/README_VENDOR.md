Forked & trimmed vendor copy
============================

This directory contains a vendorized fork of the upstream `rlex/ansible-role-k3s`.
The upstream role is available at: https://github.com/rlex/ansible-role-k3s

What we changed locally:
- Kept role runtime code (`tasks/`, `templates/`, `defaults/`, `handlers/`, `meta/`, `vars/`).
- Preserved license (`LICENSE`) and `meta/main.yml` with `license` field.
- Added `NOTICE` describing attribution.
- Provided `scripts/clean_role.sh` to remove heavy docs/CI artifacts.

If you prefer to maintain a public fork on GitHub:
1. Fork upstream: https://github.com/rlex/ansible-role-k3s
2. Push this cleaned copy to your fork and update `roles/requirements.yml` to point to your fork URL
