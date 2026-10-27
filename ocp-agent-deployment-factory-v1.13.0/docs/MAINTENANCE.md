# Documentation maintenance rules

Every change to the flow must update the documentation in the same change. Use this checklist.

| If you change... | Update |
| --- | --- |
| An inventory field (add, remove, rename, default) | `inventory/` and `inventory_templates/` (keep identical); for testing settings `testing/` and `testing_templates/` (keep identical), `INVENTORY_REFERENCE.md`, `CHANGELOG.md` |
| A playbook or stage order | `WORKFLOW.md`, `OPERATIONS.md`, `README.md` quick start, `CHANGELOG.md` |
| Validation rules in `scripts/factory.py` | `INVENTORY_REFERENCE.md` (preflight/validation scope), `OPERATIONS.md` troubleshooting, `CHANGELOG.md` |
| A template (`install-config`/`agent-config`) | `INVENTORY_REFERENCE.md`, the review checklist in `OPERATIONS.md`, `CHANGELOG.md` |
| The full preflight (`preflight()` in `scripts/factory.py`, `playbooks/preflight.yml`) or inventory validation messages | `PREFLIGHT.md`, `OPERATIONS.md`, `README.md` quick start, `CHANGELOG.md` |
| Network preflight (URLs, behaviour) | `PREFLIGHT.md`, `NETWORK_VALIDATION.md`, `CHANGELOG.md` |
| DNS/F5 checks (`scripts/netcheck.py`, `dns_checks`/`f5_checks` fields in `testing/dns_f5.yml`) | `NETWORK_VALIDATION.md`, `INVENTORY_REFERENCE.md`, `OPERATIONS.md` troubleshooting, `CHANGELOG.md`; re-test against the stubs/mocks and state what was not tested against real Infoblox/BIG-IP |
| OS packages or tools | `playbooks/dependencies.yml` (required vs optional tier), `DEPENDENCIES.md`, `BASTION_PREREQUISITES.md`, `TOOLS_AND_FALLBACKS.md` |
| A tool the checks call, or its built-in fallback (`scripts/nettools.py`, `method`/`transport`/`http_client` fields) | `TOOLS_AND_FALLBACKS.md`, `INVENTORY_REFERENCE.md`, `NETWORK_VALIDATION.md`/`PREFLIGHT.md`, `CHANGELOG.md`; test with the tool present **and** absent, and compare results |
| `templates/image_metadata.json` or the OCI archive step | `INVENTORY_REFERENCE.md`, `ARTIFACTS_AND_BACKUPS.md`, `CHANGELOG.md` |
| The approval gate, mirror or image-build proxy behaviour (`approve()`, `build()`, `mirror_data()`, `trust_data()`) | `WORKFLOW.md`, `OPERATIONS.md`, `ARTIFACTS_AND_BACKUPS.md`, `INVENTORY_REFERENCE.md`, the diagram `workflow-diagram.png`, `CHANGELOG.md` |
| Secret handling (`secret_paths()`, `secret_checks()`, the `secrets` validation, `.gitignore`) | `INVENTORY_REFERENCE.md` (Secrets), `PREFLIGHT.md`, `OPERATIONS.md`, `ARTIFACTS_AND_BACKUPS.md`, `README.md`, `CHANGELOG.md` |
| Files written to `work/` or `backups/` | `ARTIFACTS_AND_BACKUPS.md`, `CHANGELOG.md` |
| Any release | Version in `README.md` and `INVENTORY_REFERENCE.md` titles, new `CHANGELOG.md` entry stating what was and was not tested |

Rules: document limitations honestly (say what is not automated or not tested), keep `README.md` limitations current, and grep for stale version numbers and counts (for example "four inventory files") before release.
