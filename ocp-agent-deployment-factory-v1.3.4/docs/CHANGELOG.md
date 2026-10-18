# Changelog

## v1.3.4 — Documentation synchronization (2026-10-18)

- Audited v1.3.3 against the actual Python implementation, Ansible playbooks, inventory and Jinja2 templates.
- Added inventory reference, operator runbook, artifact/backup guide and manual external network-validation guide.
- Clarified the approval gate, supported OCI/Infoblox/F5 profile, exact command sequence, dependencies, and known limitations.
- Corrected documentation that implied a generated validation report or automated live Infoblox/F5 tests.
- **No deployment code changes. No live Oracle Linux 9 or OCI test performed.**

## v1.3.3

- Expanded Oracle Linux 9 prerequisites documentation and README references.

## v1.3.2

- Added dedicated bastion prerequisites guidance.

## v1.3.1

- Added Oracle Linux 9 dependency bootstrap playbook.

## v1.3

- Added inventory-driven prepare, approve, build, archive and discard stages, cluster-prefixed artifacts, QCOW2 conversion and archive/reset behavior.
