# Oracle Linux 9 bastion: prerequisite installation and validation

This document describes the **bastion host prerequisites** for the inventory-driven OpenShift Agent Deployment Factory. Run these steps on the Oracle Linux 9 host where the factory executes. This bootstrap does not modify OCI VMs, F5 or Infoblox.

## 1. One-time prerequisites (before Ansible can run)

Ansible cannot install itself through its own playbook. Install the minimal controller dependencies using an approved, reachable Oracle Linux 9 repository:

```bash
sudo dnf repolist
sudo dnf install -y python3 ansible-core
python3 --version
ansible-playbook --version
```

If `ansible-core` is unavailable, configure your organization's approved repository/mirror first. Ensure the operator has sudo privileges and that package installation is allowed.

## 2. Factory-managed OS and Python dependencies

From the project root, run:

```bash
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

`prepare.yml` and `build.yml` also import the dependency playbook. The playbook checks Oracle Linux major version 9, uses idempotent `ansible.builtin.dnf` installation, and verifies command and Python module availability.

| Category | Oracle Linux 9 package | Verification | Use |
| --- | --- | --- | --- |
| TCP probes | `nmap-ncat` | `nc` | Manual F5 VIP / API TCP port tests (the factory's own TCP probe uses Python) |
| HTTP requests | `curl` | `curl` | URL reachability preflight and endpoint probes |
| Network state | `nmstate` | `nmstatectl` | Network inspection |
| DNS tools | `bind-utils` | `dig`, `nslookup` | **Used by the factory** for the Infoblox DNS checks (`netcheck`) |
| Routing tools | `iproute` | `ip` | IP/interface/route checks |
| TLS tools | `openssl` | `openssl` | TLS diagnostics |
| Image conversion | `qemu-img` | `qemu-img` | ISO-to-QCOW2 conversion |
| Archives | `tar`, `gzip` | `tar`, `gzip` | Packaging and extraction |
| Python | `python3`, `python3-pip` | `python3` | Factory runtime |
| Python YAML | `python3-pyyaml` | `import yaml` | Parse inventory/YAML |
| Python templates | `python3-jinja2` | `import jinja2` | Render configuration |
| Ansible controller | `ansible-core` | `ansible-playbook` | One-time pre-bootstrap install |

The package manager may report a package as already installed; this is expected. Packages are only installed if missing.

## 3. Verify the environment

```bash
command -v ansible-playbook python3 nc curl nmstatectl qemu-img dig nslookup ip openssl tar gzip
python3 -c 'import yaml, jinja2; print("Python modules OK")'
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

**OpenShift installer:** `openshift-install` is not installed automatically by this dependency playbook. Obtain the approved installer matching the target OpenShift release and architecture, then verify `openshift-install version` before building. Do not assume the package repositories provide it.

## 4. Factory execution and approval gate

```bash
ansible-playbook playbooks/prepare.yml --ask-become-pass
```

`prepare` first runs the URL reachability preflight from this bastion (it needs outbound access to the URLs in `inventory/preflight.yml`, directly or via the configured proxy). Then review the generated, cluster-prefixed `install-config` and `agent-config` files and the preflight output. Use the workflow's approval stage only after confirming their contents. ISO and QCOW2 generation must remain blocked until approval. After a successful build and verified archive, the factory backs up inventory and artifacts and creates clean inventory templates for the next cluster.

See [WORKFLOW.md](WORKFLOW.md) for the complete stage sequence.

## 5. Troubleshooting and boundaries

```bash
sudo dnf repolist
sudo dnf info nmstate qemu-img python3-pyyaml python3-jinja2
ansible-playbook playbooks/dependencies.yml --ask-become-pass -vv
```

A failed DNF install may indicate disabled repositories, missing internal mirrors, package naming differences, insufficient permissions or blocked outbound access. Resolve the repository issue rather than bypassing dependency checks.

**Not yet automated:** OCI-side readiness (NSGs, routes, node-subnet DNS views), OpenShift installer download/version provisioning, and OCI boot compatibility verification. The URL preflight and the DNS/F5 checks are automated but run from this bastion only, so the bastion needs network access to the DNS resolvers, to the F5 VIPs (TCP probe) and, if used, to the BIG-IP management address (HTTPS). End-to-end Oracle Linux 9 validation is still required before production use.
