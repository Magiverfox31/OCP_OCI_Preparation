# OpenShift Agent Deployment Factory v1.12.0

Inventory-driven, sequential multi-cluster agent-image workflow. Current supported configuration: **OpenShift 4.22 family, OCI, Infoblox DNS, F5 load balancer, x86_64, exactly three masters**, on an **Oracle Linux 9 bastion**.

## Quick start

The flow has **three separate phases** (diagram: [docs/workflow-diagram.png](docs/workflow-diagram.png)).

```bash
sudo dnf install -y python3 ansible-core
ansible-playbook playbooks/dependencies.yml --ask-become-pass
# Fill inventory/{cluster,nodes,network,infrastructure}.yml (network.yml also holds NTP and the optional proxy block; cluster.yml holds the optional minimal-ISO switch, the optional mirror registry (disconnected install) and the image-build proxy mode; per host in nodes.yml you only enter name, ip and mac) and provision openshift-install

# PHASE 1 - TESTING (optional, repeatable, creates no run). Settings: testing/urls.yml and testing/dns_f5.yml
ansible-playbook playbooks/preflight.yml                    # ALL checks (inventory, tools, URLs or mirror registry, DNS) without stopping at the first failure; PASSED/WARNINGS/FAILED summary, saved to work/preflight-<time>.log
ansible-playbook playbooks/netcheck.yml                     # optional: only the DNS (and, if enabled, F5) checks

# PHASE 2 - CONFIGURATION FILES (create, edit, approve)
ansible-playbook playbooks/prepare.yml --ask-become-pass   # creates install-config.yaml, agent-config.yaml, image_metadata.json (no connectivity tests)
# EDIT the files in work/<cluster>/<run-id>/review/ if you want to change anything
ansible-playbook playbooks/approve.yml -e run_id=<run-id>  # checks your edits, shows a diff, records the approval

# PHASE 3 - IMAGE
ansible-playbook playbooks/build.yml --ask-become-pass     # ISO, qcow2 and master_node_image.oci
ansible-playbook playbooks/archive.yml
```

**What it does:** (0) installs the Oracle Linux 9 packages the build requires, plus optional diagnostic tools; **Phase 1, testing:** (1) `preflight.yml` runs all checks - inventory validation, tools, the OCP allowlist URLs (`testing/urls.yml`) or, for a disconnected install, the mirror registry, and DNS (Infoblox) / optional F5 - and prints a PASSED/WARNINGS/FAILED summary; **Phase 2, configuration files:** (2) `prepare.yml` creates `install-config.yaml` (including `clusterNetwork`, `serviceNetwork`, the optional `proxy` section and the optional mirror `imageContentSources` + CA) and `agent-config.yaml` from the inventory, (3) you may edit them, then `approve.yml` checks them and records the approval; **Phase 3, image:** (4) `build.yml` builds the agent ISO (with the proxy mode you chose), converts it to QCOW2 and packs the QCOW2 with `image_metadata.json` into `master_node_image.oci` for manual upload to an OCI bucket.

The ISO and QCOW2 are **blocked until explicit approval**, and the approval covers the files exactly as you leave them after editing (editing again after approval requires approving again). Archive copies and checksum-verifies inventory and artifacts (plus the newest preflight log) before resetting `inventory/` and `testing/` from `inventory_templates/` and `testing_templates/`. One active run per checkout. This factory does not provision OCI, configure Infoblox/F5, or guarantee OCI boot compatibility. `prepare` does not require a passing preflight: running the testing phase first is your decision.

## Documentation

- [Operator runbook](docs/OPERATIONS.md)
- [Complete workflow and approval gate](docs/WORKFLOW.md)
- [Oracle Linux 9 bastion prerequisites](docs/BASTION_PREREQUISITES.md)
- [Dependency matrix](docs/DEPENDENCIES.md)
- [Inventory field reference](docs/INVENTORY_REFERENCE.md)
- [Artifact naming, backup and security](docs/ARTIFACTS_AND_BACKUPS.md)
- [URL reachability preflight](docs/PREFLIGHT.md)
- [DNS (Infoblox) and F5 BIG-IP checks, plus manual OCI checks](docs/NETWORK_VALIDATION.md)
- [Blocked or missing tools (ping, dig, curl, nc) and built-in fallbacks](docs/TOOLS_AND_FALLBACKS.md)
- [Release changelog](docs/CHANGELOG.md)
- [Documentation maintenance rules](docs/MAINTENANCE.md)

## Limitations and verification

- `openshift-install` must be separately installed and match the inventory version.
- The preflight proves the **bastion** can reach the listed URLs; it does not prove the OCI nodes can. The DNS/F5 checks (`netcheck`) also run from the bastion; they were tested only against a `dig` stub and a mock BIG-IP REST API, **not** a real Infoblox or BIG-IP (see NETWORK_VALIDATION.md).
- The proxy section only configures the **cluster-wide proxy** in `install-config.yaml`. It does not set the bastion's own proxy; export `http_proxy`/`https_proxy` in the shell if the bastion needs one to download from Red Hat.
- The shipped URL list is a starting point; verify it against the Red Hat OpenShift 4.22 documentation for your environment.
- The checks never use ICMP (ping) and keep working when `dig` or `curl` are missing or UDP/53 is blocked, by using built-in Python clients; see [TOOLS_AND_FALLBACKS.md](docs/TOOLS_AND_FALLBACKS.md). Those fallbacks were tested against mock servers only, not a real Infoblox/BIG-IP/Oracle Linux 9 host.
- Test results are written to `work/preflight-<time>.log` and `.json` (no per-run test reports any more); the newest pair is copied into each archive.
- ISO-to-QCOW2 conversion is not proof of OCI boot compatibility. The `master_node_image.oci` archive (qcow2 + `image_metadata.json`) is built and its contents are verified locally, but it has **not** been imported into OCI; the factory does not upload it (you upload it to your bucket manually).
- Python/YAML and archive integrity checks are local only; **no end-to-end deployment validation has been performed**.
- Treat configuration and backup data as sensitive; keep pull secrets outside source control and protect backups.
