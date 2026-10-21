# Changelog

## v1.6.0 — DNS (Infoblox) and F5 BIG-IP checks (2026-10-21)

- **Added** `netcheck` stage (`scripts/netcheck.py`, `playbooks/netcheck.yml`), run automatically by `prepare` after the URL preflight; bypass with `-e skip_netcheck=true` (or `FACTORY_SKIP_NETCHECK=true`). Any `FAIL` stops `prepare` before a run is created; `WARN` never blocks. Result saved as `netcheck-report.json` (no credentials) and archived.
- **Added DNS checks** (`dig` against every configured resolver): `api`, `api-int`, a random-label probe proving the `*.apps` wildcard, and each node's forward A and reverse PTR record. Reports `REFUSED` (Infoblox ACL/views), `NXDOMAIN`, `SERVFAIL`, wrong address and no-reply distinctly; an unusable resolver is reported once.
- **Added F5 BIG-IP checks**: optional read-only iControl REST audit (virtual servers for api 6443, MCS 22623, ingress 443/80 exist, are enabled and have a pool containing the expected nodes; pool monitor, member ports, self IPs) and an optional TCP probe (`off`/`warn`/`require`, default `warn`). The REST password comes only from an environment variable or file, never the inventory, and is passed to curl on stdin.
- **Added** inventory blocks `infrastructure.dns_checks` and `infrastructure.f5_checks` (identical in `inventory_templates/`), validation that VIPs are not node IPs, and `docs/NETWORK_VALIDATION.md` rewritten as the reference for these checks.
- **Changed** `prepare.yml`, `preflight.yml` and `netcheck.yml` now print the full report before failing, so errors are readable in Ansible output. `prepare.yml` passes the skip switches to the script through environment variables.
- Tested locally with a `dig` stub that emits genuine dig output format and a TLS mock of the iControl REST API (healthy and misconfigured BIG-IP, bad/missing credentials, TLS verification failure, route-domain VIPs, passwords containing quotes/backslashes, TCP probe modes, gating of `prepare`, full prepare/approve/build/archive). **Not tested against a real `dig`, Infoblox grid or BIG-IP**; the iControl REST field names used (`destination`, `pool`, `membersReference`, `address`) follow the documented API and should be confirmed on your BIG-IP version.

## v1.5.0 — Proxy section and network validation (2026-10-21)

- **Added** optional `proxy:` block in `inventory/network.yml`, rendered as `proxy` (`httpProxy`, `httpsProxy`, `noProxy`) plus optional `additionalTrustBundle`/`additionalTrustBundlePolicy` in `install-config.yaml`. Omitted entirely when `enabled: false`. `noProxy` automatically includes localhost, `.svc`, `.cluster.local`, `api-int.<cluster>.<base_domain>` and the machine/cluster/service networks.
- **Added** validation: proxy URLs must be `http://`, trust bundle must be a readable PEM file, and `machine_network`, `cluster_network` and `service_network` must not overlap; `host_prefix` must be larger than the cluster network prefix.
- **Clarified** that `install-config.yaml` already rendered `clusterNetwork` and `serviceNetwork` from the inventory; no change to those sections beyond the new validation.
- **Changed** template rendering now trims Jinja block whitespace (no stray blank lines in the generated YAML).
- Added `docs/MAINTENANCE.md` (which docs to update for each kind of change).
- Tested locally (proxy disabled/enabled, trust bundle, overlap, bad `host_prefix`, `https://` proxy rejected). Not tested with a real `openshift-install` or proxy.

## v1.4.0 — Preflight and fixes (2026-10-21)

- **Added** OCP allowlist URL reachability preflight (`inventory/preflight.yml`, `playbooks/preflight.yml`, automatic in `prepare`; `-e skip_preflight=true` to bypass). Report saved as `preflight-report.json` and archived. See `docs/PREFLIGHT.md`.
- **Fixed** `playbooks/prepare.yml` and `playbooks/build.yml`: each contained two YAML documents and could not be loaded by `ansible-playbook`. Each is now a single document (`import_playbook` + play).
- **Fixed** `install-config.yaml.j2` hardcoded `compute.replicas: 0`; it is now the number of `worker` hosts, matching `agent-config.yaml`.
- **Fixed** build crash after QCOW2 conversion (`json.loads` received the process object instead of its output).
- **Fixed** build retry after failure: `openshift-install` consumes its input files, so the retry hash check failed. Inputs are now restored from the approved review files.
- **Fixed** `cluster.release_image` had no effect; it is now passed to the installer via `OPENSHIFT_INSTALL_RELEASE_IMAGE_OVERRIDE`.
- **Removed** unused `boot_mac_address` from the inventory comment and reference.
- Tested locally with stub `openshift-install`/`qemu-img` binaries and a local HTTP server (preflight pass/fail, prepare, approve, failed then retried build, archive). **Not tested on a real Oracle Linux 9 host, with real `ansible-playbook`, `openshift-install`, or OCI.**

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
