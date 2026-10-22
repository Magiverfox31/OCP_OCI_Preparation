# OpenShift Agent Deployment Factory v1.7.0

Inventory-driven, sequential multi-cluster agent-image workflow. Current supported configuration: **OpenShift 4.22 family, OCI, Infoblox DNS, F5 load balancer, x86_64, exactly three masters**, on an **Oracle Linux 9 bastion**.

## Quick start

```bash
sudo dnf install -y python3 ansible-core
ansible-playbook playbooks/dependencies.yml --ask-become-pass
# Fill inventory/{cluster,nodes,network,infrastructure,preflight}.yml (network.yml also holds the optional proxy block) and provision openshift-install
ansible-playbook playbooks/preflight.yml                    # optional: check OCP allowlist URLs on their own
ansible-playbook playbooks/netcheck.yml                     # optional: DNS (Infoblox) and F5 BIG-IP checks on their own (export F5_PASSWORD first if using the F5 REST audit)
ansible-playbook playbooks/prepare.yml --ask-become-pass   # runs the URL preflight and the DNS/F5 checks, then renders configs
# REVIEW work/<cluster>/<run-id>/review/<cluster>-*.yaml
ansible-playbook playbooks/approve.yml -e run_id=<run-id>
ansible-playbook playbooks/build.yml --ask-become-pass
ansible-playbook playbooks/archive.yml
```

**What it does:** (1) installs the Oracle Linux 9 packages the build requires, plus optional diagnostic tools (a blocked optional package does not stop the run), (2) probes the OCP allowlist URLs from the bastion (preflight, list in `inventory/preflight.yml`) and checks DNS (Infoblox) and F5 BIG-IP readiness (`netcheck`, configured in `inventory/infrastructure.yml`), (3) renders `install-config.yaml` (including `clusterNetwork`, `serviceNetwork` and the optional `proxy` section) and (4) `agent-config.yaml` from the inventory, (5) builds the agent ISO and (6) converts it to QCOW2.

The ISO and QCOW2 are **blocked until explicit approval**. Archive copies and checksum-verifies inventory and artifacts before resetting inventory from `inventory_templates/`. One active run per checkout. This factory does not provision OCI, configure Infoblox/F5, or guarantee OCI boot compatibility.

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
- Reports are written as JSON per run (`preflight-report.json`, `netcheck-report.json`); there is no combined human-readable validation report.
- ISO-to-QCOW2 conversion is not proof of OCI boot compatibility.
- Python/YAML and archive integrity checks are local only; **no end-to-end deployment validation has been performed**.
- Treat configuration and backup data as sensitive; keep pull secrets outside source control and protect backups.
