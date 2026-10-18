# Artifact naming, approvals and backups

The factory uses **standard** `install-config.yaml` and `agent-config.yaml` names in the isolated installer working directory. Published review and backup files use the cluster prefix.

For `ocp-uat`, the published files are:
- `ocp-uat-install-config.yaml`
- `ocp-uat-agent-config.yaml`
- `ocp-uat-agent.x86_64.iso`
- `ocp-uat-agent.x86_64.qcow2`

`work/<cluster>/<run-id>/` contains `inventory/` (snapshot), `review/` (cluster-prefixed YAML), `installer/` (standard installer names), `run.json` (run state, hashes and approval), and, after build, `artifacts/`. `work/active-run.json` points to the active run.

`backups/<cluster>/<run-id>/` contains `inventory/`, `review/`, `artifacts/`, `run.json`, and `checksums.json`. The archive routine copies and SHA-256 verifies its payload before resetting the four active inventory files from `inventory_templates/`. The original work directory is retained.

## Approval gate

`prepare` generates the YAML and hashes them. The operator reviews the **cluster-prefixed review files**. `approve -e run_id=...` checks that the review files and active/snapshotted inventory are unchanged, then records approval. `build` rechecks the hashes and refuses unapproved runs. This is a command-line approval record, **not** a web interface or a cryptographic signature.

To correct inventory after preparing, run `ansible-playbook playbooks/discard.yml -e run_id=<run-id>` and then prepare again. Discard only removes the active-run marker; it preserves the prior run workspace. Do not edit the generated installer files directly.

## Security and recovery

The inventory snapshot and generated configuration may contain or reference sensitive material. Use restricted permissions, encrypted backups, and a secure storage policy. The factory does not upload backups off-host, automatically prune them, or restore them. `archive` can fail partway through the inventory reset; check the inventory before starting a new run. Avoid concurrent runs in the same checkout.

QCOW2 format verification does **not** establish OCI import/boot compatibility. Test the generated image with the target OCI boot workflow.
