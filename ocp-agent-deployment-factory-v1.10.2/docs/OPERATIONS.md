# Operator runbook — Oracle Linux 9

From the extracted project root, with approved DNF repositories and sudo rights:

```bash
sudo dnf install -y python3 ansible-core
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

Install an approved `openshift-install` binary matching the target OCP release separately and confirm `openshift-install version`. Ensure `python3 -c 'import yaml, jinja2'` succeeds.

1. Fill in the five `inventory/*.yml` files (`cluster`, `nodes`, `network`, `infrastructure`, `preflight`). In `nodes.yml` set the shared values once under `node_defaults` (NIC name, root disk) and add each host with only `name`, `ip` and `mac`; gateway, DNS and NTP come from `network.yml` (see [INVENTORY_REFERENCE.md](INVENTORY_REFERENCE.md)). Keep real pull secrets outside source control.
2. If you enabled the F5 REST audit (`infrastructure.f5_checks.rest`), export the read-only password first: `export F5_PASSWORD=...` (or use `password_file`). Run `ansible-playbook playbooks/prepare.yml --ask-become-pass`. It first probes the allowlist URLs (see [PREFLIGHT.md](PREFLIGHT.md)) and then the DNS (Infoblox) and F5 BIG-IP checks (see [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md)). To run a check alone use `playbooks/preflight.yml` or `playbooks/netcheck.yml`; to bypass one deliberately add `-e skip_preflight=true` or `-e skip_netcheck=true`.
3. Read `work/<cluster>/<run-id>/review/<cluster>-install-config.yaml` and `<cluster>-agent-config.yaml`. Check addresses, host roles, MACs, the interface name, `mtu` (if set) and `rootDeviceHints` on every host, `minimalISO` (`true` means each node downloads the rootfs at boot), `additionalNTPSources`, CIDRs (install-config worker `replicas` must equal the number of worker hosts), the `clusterNetwork`/`serviceNetwork` blocks, the `proxy` section (when enabled: proxy URLs, the generated `noProxy` list and the trust bundle), pull-secret handling, and expected DNS/F5 endpoints. The URL preflight and DNS/F5 results are stored in `work/<cluster>/<run-id>/preflight-report.json` and `netcheck-report.json`; review any `WARN` lines from the console output too.
4. Run `ansible-playbook playbooks/approve.yml -e run_id=<run-id>` only after review.
5. Run `ansible-playbook playbooks/build.yml --ask-become-pass` to create ISO and QCOW2.
6. Validate the image against OCI import and boot requirements **before production use**.
7. Run `ansible-playbook playbooks/archive.yml` to copy/verify the backup and reset the active inventory.

If `build` fails, fix the cause and run `build.yml` again; installer inputs are restored from the approved review files. For rejection: `ansible-playbook playbooks/discard.yml -e run_id=<run-id>`; update inventory and prepare again. An interrupted build may still need manual inspection of its working directory.

**Warning:** `archive` resets the active inventory (so run `playbooks/netcheck.yml` with `tcp_probe: "require"` after the nodes are up and *before* archive if you want a live load-balancer check) after a verified archive; keep a second secure backup of critical inputs. One active run per checkout; parallel cluster builds require separate checkouts.

## Troubleshooting

- `dnf` fails: inspect `sudo dnf repolist`, repositories and proxy. A failure on a *required* package (python3, PyYAML, Jinja2, qemu-img, nmstate, tar, gzip) stops the run; a failure on an *optional* one (curl, bind-utils, nmap-ncat, iproute, openssl, python3-pip) only prints a note.
- A tool is missing or blocked (ping, dig, curl, nc): the factory never uses ping, and uses built-in Python DNS/HTTP clients when `dig`/`curl` are absent. The line `NETCHECK tools:` (and `(client: ...)` in the preflight summary) shows which one ran. If UDP/53 is blocked, the resolver gets a `WARN` and is checked over TCP. Manual alternatives are in [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md).
- Python import fails: check `python3-pyyaml` and `python3-jinja2` availability.
- Installer missing/mismatched: check `command -v openshift-install` and `openshift-install version`.
- DNS/F5 check fails: each `FAIL` line names the record or virtual server and the reason. `REFUSED` = the Infoblox allow-query ACL/views do not permit the bastion address; `NXDOMAIN` = record missing; `got X, expected Y` = wrong address; `SERVFAIL` = resolver/zone problem; `no reply` = routing or firewall. F5 `missing control-plane nodes` = the pool lacks inventory nodes; `no virtual server` = no VIP:port destination on the BIG-IP; HTTP 401/403 = bad credentials or a role that cannot read LTM objects. Details in [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md). Run `ansible-playbook playbooks/netcheck.yml` to re-test without creating a run.
- Several inventory errors at once: run `ansible-playbook playbooks/preflight.yml` first. It lists every inventory problem (file, field, value), checks the tools, URLs and DNS, and prints a PASSED/WARNINGS/FAILED summary, also saved in `work/preflight-<time>.log`.
- Preflight fails: each blocked URL is listed with the curl error (`Could not resolve host` = DNS, `timed out` = firewall, `SSL certificate problem` = TLS inspection; set `preflight.ca_bundle` or `proxy`). Fix the network path or remove a URL you intentionally do not use from `inventory/preflight.yml`.
- Validation error about overlapping networks, `host_prefix`, or proxy: fix `inventory/network.yml` (`cluster_network`, `service_network` and `machine_network` must not overlap; proxy URLs must be `http://`).
- `nodes.yml` error (`missing "mac"`, `unknown key(s)`, `not inside network.machine_network`, `no interface`, `Duplicate host`): the message names the host and the problem; fix `inventory/nodes.yml` (or `network.yml` for the machine network and NTP) and run prepare again.
- Approval rejected: check whether inventory or review files changed; discard and re-prepare.
- ISO/QCOW2 failure: inspect the preserved `work/<cluster>/<run-id>/` and verify disk space, installer logs and `qemu-img info`.
- Node boots the image but cannot continue and `minimalISO` is `true`: the node subnet cannot reach the rootfs download URL. Allow it (check the node subnet's routes, NSGs and proxy/firewall rules) or set `cluster.minimal_iso: false` and rebuild.
- Build stops with `OCI archive verification failed` or an `image_metadata.json` error: the template is invalid JSON or the archive contents differ from the expected two files; fix `templates/image_metadata.json` and re-prepare.
- OCI boot failure: image format alone is insufficient; validate OCI image import/firmware requirements.

See [BASTION_PREREQUISITES.md](BASTION_PREREQUISITES.md), [INVENTORY_REFERENCE.md](INVENTORY_REFERENCE.md), [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md) and [ARTIFACTS_AND_BACKUPS.md](ARTIFACTS_AND_BACKUPS.md).
