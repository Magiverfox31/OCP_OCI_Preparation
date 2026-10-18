# OpenShift Agent Deployment Factory v1.3.4

Inventory-driven, sequential multi-cluster agent-image workflow. Current supported configuration: **OpenShift 4.22 family, OCI, Infoblox DNS, F5 load balancer, x86_64, exactly three masters**, on an **Oracle Linux 9 bastion**.

## Quick start

```bash
sudo dnf install -y python3 ansible-core
ansible-playbook playbooks/dependencies.yml --ask-become-pass
# Fill inventory/{cluster,nodes,network,infrastructure}.yml and provision openshift-install
ansible-playbook playbooks/prepare.yml --ask-become-pass
# REVIEW work/<cluster>/<run-id>/review/<cluster>-*.yaml
ansible-playbook playbooks/approve.yml -e run_id=<run-id>
ansible-playbook playbooks/build.yml --ask-become-pass
ansible-playbook playbooks/archive.yml
```

The ISO and QCOW2 are **blocked until explicit approval**. Archive copies and checksum-verifies inventory and artifacts before resetting inventory from `inventory_templates/`. One active run per checkout. This factory does not provision OCI, configure Infoblox/F5, or guarantee OCI boot compatibility.

## Documentation

- [Operator runbook](docs/OPERATIONS.md)
- [Complete workflow and approval gate](docs/WORKFLOW.md)
- [Oracle Linux 9 bastion prerequisites](docs/BASTION_PREREQUISITES.md)
- [Dependency matrix](docs/DEPENDENCIES.md)
- [Inventory field reference](docs/INVENTORY_REFERENCE.md)
- [Artifact naming, backup and security](docs/ARTIFACTS_AND_BACKUPS.md)
- [Manual OCI, Infoblox and F5 validation](docs/NETWORK_VALIDATION.md)
- [Release changelog](docs/CHANGELOG.md)

## Limitations and verification

- `openshift-install` must be separately installed and match the inventory version.
- Package installation checks tools, **not** live DNS/F5 readiness.
- No separate validation report is produced.
- ISO-to-QCOW2 conversion is not proof of OCI boot compatibility.
- Python/YAML and archive integrity checks are local only; **no end-to-end deployment validation has been performed**.
- Treat configuration and backup data as sensitive; keep pull secrets outside source control and protect backups.
