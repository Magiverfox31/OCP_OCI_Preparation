# Deployment workflow and mandatory review gate

1. **Bootstrap dependencies**: `playbooks/dependencies.yml` runs explicitly or as part of prepare/build. Oracle Linux 9 only.
2. **Prepare**: `playbooks/prepare.yml` validates inventory and generates the two configuration files. It creates a run ID, inventory snapshot, and hashes.
3. **Human review**: inspect the files under `work/<cluster>/<run-id>/review/`. No ISO is created at this stage.
4. **Approve**: `playbooks/approve.yml -e run_id=<run-id>` records approval only if review files and inventory still match their recorded hashes.
5. **Build**: `playbooks/build.yml` validates approval, checks `openshift-install`, creates the ISO, converts it to QCOW2, and verifies QCOW2 format.
6. **Archive**: `playbooks/archive.yml` copies the inventory, YAML, ISO and QCOW2 into `backups/<cluster>/<run-id>/`, verifies checksums, then resets active inventory from clean templates.
7. **Next cluster**: populate the fresh inventory and repeat.

To reject, use `playbooks/discard.yml -e run_id=<run-id>` and prepare again.

**Implementation boundaries:** The workflow supports one active run per checkout. External Infoblox/F5/OCI readiness checks and OCI image bootability are not automated. There is no separate validation-report file generated. Consult [OPERATIONS.md](OPERATIONS.md) for exact commands.
