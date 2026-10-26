# Changelog

## v1.12.0 — Three phases: editable configs, mirror option, image-build proxy mode (2026-10-26)

- **Changed** the flow is now three phases: (1) testing (`preflight.yml`, unchanged), (2) configuration files: `prepare` creates them, you may edit them, `approve` records the approval, (3) image build (`build.yml`). `archive` follows.
- **Changed** `approve` now accepts hand edits to the files in `review/`. It validates each file (YAML/JSON syntax with line and column; `metadata.name` unchanged; `AgentConfig` kind, `rendezvousIP`, `hosts`; `baseDomain`, `networking`, `pullSecret`), copies the final files to `installer/`, prints a diff against the untouched `generated/` copy (secret lines never shown), saves it as `approval-diff.txt`, and records `approved_checksums`. Before, any edit made the approval fail. `build` verifies the approved hashes, so editing after approval still needs a new approval. A file that fails the checks leaves the run awaiting approval. `generated/` and `approval-diff.txt` are archived.
- **Added** `cluster.mirror` (disconnected install): `enabled`, `registry`, `sources`, `sources_key` (`imageContentSources` default, or `imageDigestSources`), `ca_bundle_file`. Renders the mirror sources and the registry CA in `install-config.yaml` (`additionalTrustBundle`, policy `Always`; joined with the proxy CA if both exist), adds the registry host to `noProxy` when the proxy is on, and notes an empty `release_image`. The testing phase tests the registry instead of the public URL list (`urls_when_mirror`, `mirror_probe_via_proxy` in `testing/urls.yml`).
- **Added** `cluster.image_build.proxy` (`inherit` default, `cluster`, `none`): the proxy variables `openshift-install` sees during the build. The existing `network.yml` `proxy.enabled` switch still controls the cluster proxy in `install-config.yaml`.
- **Added** the workflow diagram, `docs/workflow-diagram.png`.
- Tested locally with stub tools: edit then approve (diff shown, installer got the edits), broken or renamed edits refused, edit after approval refused at build, mirror + proxy + CA install-config render, all three proxy modes (the installer stub saw the expected variables), the disconnected URL test, and a full archive. **Not tested:** a real `openshift-install` in a disconnected environment, a real mirror registry, or OCI import. The `imageContentSources` shape follows Red Hat's 4.22 agent-based installer documentation; `imageDigestSources` is offered through `sources_key` but was not verified against the 4.22 installer.

## v1.11.0 — Testing phase separated from the build flow (2026-10-26)

- **Changed** `prepare` no longer runs the URL preflight or the DNS/F5 checks and no longer writes `preflight-report.json` / `netcheck-report.json` into the run. It only validates the build inventory and renders the configs. `-e skip_preflight` / `-e skip_netcheck` and the matching environment variables and script flags were removed (nothing to skip).
- **Added** the `testing/` folder (with clean copies in `testing_templates/`): `urls.yml` (the former `inventory/preflight.yml`) and `dns_f5.yml` (the `dns_checks` and `f5_checks` blocks, now top-level keys, moved out of `infrastructure.yml`). `prepare`, `approve` and `build` never read it. `archive` resets it from `testing_templates/` like the inventory.
- **Changed** the build inventory is now four files (`cluster`, `nodes`, `network`, `infrastructure`). `f5_self_ips` stays in `infrastructure.yml` and is required only when the F5 checks are enabled (checked by the testing phase).
- **Changed** `playbooks/preflight.yml` also validates `testing/` and reports a leftover `inventory/preflight.yml` as a warning. `playbooks/netcheck.yml` reads `testing/dns_f5.yml`.
- **Changed** `archive` copies the newest `work/preflight-*.log` and `.json` into the backup (it may belong to an earlier run).
- **Migration:** move your `preflight:` block to `testing/urls.yml` and your `dns_checks`/`f5_checks` blocks to `testing/dns_f5.yml`, delete `inventory/preflight.yml`, and remove the two blocks from `infrastructure.yml` (leaving them there is reported as an error so settings are not silently ignored).
- Tested locally with stubs: prepare with the `testing/` files deleted, the full preflight reading `testing/`, the old-layout error, and a full prepare/approve/build/archive run with the testing files reset afterwards. Not tested under real Ansible or on Oracle Linux 9.

## v1.10.2 — Coloured preflight report (2026-10-22)

- **Added** colours to the full preflight report: `PASS` green, `FAIL` red, `WARN` yellow, plus the summary counts, the FAILED/WARNINGS lists and the `RESULT:` line. `scripts/factory.py preflight --color` enables it; `playbooks/preflight.yml` uses it automatically when a terminal is available (it writes to `/dev/tty`, because Ansible would print the colour codes as text) and falls back to the plain report otherwise. The saved log and JSON files stay plain.
- Tested: the colour output, and the playbook's shell logic with a terminal and without one (plain output, no colour codes, same exit code). **Not tested:** the playbook under real Ansible (not installed in the test environment); if the colours do not appear in your session, run `python3 scripts/factory.py preflight --color` directly.

## v1.10.1 — Full preflight with summary, clearer inventory errors, F5 off (2026-10-22)

- **Changed** `playbooks/preflight.yml` (stage `preflight`) now runs every check without stopping at the first failure: inventory, tools (including the `openshift-install` version), all URLs and the DNS checks. It prints a PASSED/WARNINGS/FAILED summary and writes `work/preflight-<UTC time>.log` and `.json`. It exits non-zero only after everything has run if anything failed. `prepare` is unchanged and still stops at the first failing stage.
- **Changed** inventory validation can report all problems at once (used by the full preflight). Every message now names the file, the field and the rejected value, for example `api_vip ... must be an IP address, got 'api.example'`, MAC values that contain an interface name, a `ntp_servers` string instead of a list, a `pull_secret_file` that is not a path, and YAML syntax errors with file, line and column.
- **Changed** F5 checks are now off by default (`f5_checks.enabled: false` in `inventory/` and `inventory_templates/`) and are not run by preflight, netcheck or prepare. `f5_self_ips` is required only while they are enabled. Set `enabled: true` to use them again.
- Tested locally: broken-inventory run listing six problems at once, a good inventory, F5 disabled with empty `f5_self_ips`, and the full prepare/approve/build/archive run. Not tested: real URLs/proxy, a real Infoblox, or Oracle Linux 9. The URL and DNS FAIL lines seen in the sandbox came from the sandbox network and test stubs, not from the factory.

## v1.10.0 — OCI import archive master_node_image.oci (2026-10-22)

- **Added** `templates/image_metadata.json` (content supplied by the operator: UEFI_64, PARAVIRTUALIZED, `Custom` OS). Prepare validates it as JSON and stores it in `review/` as `<cluster>-image_metadata.json`, so it is covered by the approval hash.
- **Added** a final build step that creates `artifacts/master_node_image.oci`: an uncompressed tar with `image_metadata.json` and the cluster QCOW2 at the top level (normalised owner root, mode 0644). The entry list is verified. The file name is fixed. Upload to the OCI bucket remains manual.
- **Fixed** the approved-run check compared every reviewed file with the installer directory; it now compares only `install-config.yaml` and `agent-config.yaml`. Build retry restores only those two files.
- Tested locally with stub `openshift-install`/`qemu-img`: prepare, approve, build, archive, tar contents and metadata identical to the template. **Not tested:** import of the archive into OCI, boot of the image, a real `openshift-install`. The tar layout follows OCI's exported-image format as understood; confirm with the first import.

## v1.9.1 — Standard values: minimalISO true, MTU 9000 (2026-10-22)

- **Changed** the standard value of `cluster.minimal_iso` from `false` to `true`, in the inventory files and as the built-in value when the key is missing.
- **Changed** `node_defaults.mtu: 9000` is now set in the inventory files (it was a commented example), and 9000 is also the built-in value for any host that has no `mtu`, so every host always gets `mtu: 9000` unless a host sets a different value.
- **Effect on upgrades:** inventories from v1.9.0 or earlier that omitted these keys now produce `minimalISO: true` and `mtu: 9000`. Set `minimal_iso: false` or a different `mtu` to change that. Nodes must be able to reach the rootfs download URL (see NETWORK_VALIDATION.md), and the network path must support jumbo frames.

## v1.9.0 — Minimal ISO switch and MTU (2026-10-22)

- **Added** `cluster.minimal_iso` (default `false` in v1.9.0; `true` since v1.9.1), rendered as `minimalISO:` in `agent-config.yaml` (after `rendezvousIP`, before `additionalNTPSources`). `true` builds an ISO without the rootfs, which each node downloads during installation. Must be a YAML boolean. Inventories from earlier versions without the key behave as `false`.
- **Added** `node_defaults.mtu` and per-host `mtu` (whole number 576-9216), rendered as `mtu:` on the host interface in `networkConfig`. Unset by default in v1.9.0 (9000 since v1.9.1).
- **Changed** the blank `nodes.yml` template no longer pre-fills the NIC name (`interface: ""`), so the operator must choose it (for example `enp0s5` or `ens3`); the prepare stage reports a missing interface per host. The MTU line is commented out in the template.
- **Checked against Red Hat documentation:** `minimalISO` (boolean, default false, ISO without rootfs), `additionalNTPSources` (list added to all hosts), and `mtu`, `mac-address`, `table-id: 254` in the documented `networkConfig` examples. The generated output matches a Red Hat Consulting reference agent-config supplied by the user, apart from `mac-address` and `table-id: 254` (present in Red Hat's own example) and quoted NTP values.
- Tested locally with an inventory modelled on that reference (FQDN host names, `enp0s5`, MTU 9000, two NTP servers, `minimalISO: true`), the default and absent-key cases, per-host MTU override, invalid values, and a full prepare/approve/build/archive run. Not tested with a real `openshift-install`.

## v1.8.0 — Shared node settings (2026-10-22)

- **Changed** `inventory/nodes.yml`: hosts are listed under `masters:` and `workers:` and need only `name`, `ip` and `mac`. NIC name and root disk are set once in `node_defaults`; the subnet prefix is derived from `network.machine_network`; gateway and DNS continue to come from `network.yml`. Any shared value can be overridden on a single host. The older `nodes:` list with `role:` per host still works (and also honours `node_defaults`). Mixing both formats is rejected.
- **Added** `network.ntp_servers` (shared by all hosts), rendered as `additionalNTPSources` in `agent-config.yaml`; omitted when empty. NTP is cluster-wide in the agent config, not per host.
- **Added** validation: unknown host or `node_defaults` keys are rejected (a typo such as `root_device_hints` was previously ignored silently), each node IP must be inside `network.machine_network`, `root_device_hint` must start with `/dev/`, `ntp_servers` entries must be host names or IPs, and the duplicate-host error now names the host and the repeated value.
- Tested locally: five-host minimal inventory with a per-host override, older format, empty NTP, ten error cases, and a full prepare (with DNS checks) / approve / build / archive run. Not tested with a real `openshift-install`; confirm that it accepts the generated `additionalNTPSources` and `rootDeviceHints`.

## v1.7.0 — Fallbacks for blocked or missing tools (2026-10-22)

- **Clarified** that no stage uses ICMP (ping); reachability is tested with DNS queries, HTTP requests and TCP connects. New page `docs/TOOLS_AND_FALLBACKS.md` lists every tool, its fallback, the override setting and manual alternatives (ping, traceroute, dig, nc, curl, openssl, ip).
- **Added** built-in Python DNS client (`scripts/nettools.py`, standard library only) used when `dig` is not installed or `dns_checks.method: "builtin"`. UDP first, TCP fallback, compression, truncation and wrong-ID handling.
- **Added** UDP-to-TCP fallback for DNS (`dns_checks.transport`, default `auto`): a resolver that answers only over TCP/53 is checked over TCP and reported once as a `WARN` (works with both `dig`, via `+tcp`, and the built-in client). When both transports fail the error names each.
- **Added** built-in Python HTTP client used when `curl` is not installed or forced (`preflight.http_client`, `infrastructure.f5_checks.rest.http_client`, default `auto`), with proxy, CA bundle, TLS verify and basic-auth support and curl-like error wording.
- **Changed** `playbooks/dependencies.yml` now has required packages (python3, PyYAML, Jinja2, qemu-img, nmstate, tar, gzip: stop on failure) and optional packages (curl, bind-utils, nmap-ncat, iproute, openssl, python3-pip: failure only prints what the factory does instead). Previously a missing `nc`, `dig` or `nslookup` stopped the run.
- **Changed** the URL preflight (curl path) no longer follows redirects, matching the built-in client: any HTTP answer, including 301, means reachable.
- **Added** to the reports: `client` in `preflight-report.json`, `tools` in `netcheck-report.json`, and a `NETCHECK tools:` line in the output.
- Tested locally with `dig` and `curl` removed from `PATH`: DNS mock server (real wire protocol, UDP+TCP), HTTP/HTTPS servers, a forward proxy (plain and CONNECT), a mock BIG-IP, and a full prepare/approve/build/archive run; results compared with the `dig`/`curl` paths. **Not tested on a real Oracle Linux 9 host (Python 3.9 was only checked for syntax), real `ansible-playbook`, Infoblox, BIG-IP or proxy.** The edited `dependencies.yml` could not be run because Ansible is not available in the test environment.

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
