# Artifact naming, approvals and backups

The factory uses **standard** `install-config.yaml` and `agent-config.yaml` names in the isolated installer working directory. Published review and backup files use the cluster prefix.

For `ocp-uat`, the published files are:
- `ocp-uat-install-config.yaml`
- `ocp-uat-agent-config.yaml`
- `ocp-uat-agent.x86_64.iso`
- `ocp-uat-agent.x86_64.qcow2`
- `ocp-uat-image_metadata.json` (the approved OCI launch metadata)
- `master_node_image.oci` (the OCI import archive; the name is fixed and has no cluster prefix)

`master_node_image.oci` is an uncompressed tar with exactly two entries at its top level: `image_metadata.json` (identical to the approved copy) and `ocp-uat-agent.x86_64.qcow2`. Build verifies the entry list. Upload it to your OCI bucket manually and import it as a custom image. List the contents with `tar tvf master_node_image.oci`. Because the name is fixed, archives of different clusters keep it under their own `backups/<cluster>/<run-id>/artifacts/`; rename it if you collect several in one bucket.

`work/<cluster>/<run-id>/` contains `inventory/` (snapshot), `review/` (cluster-prefixed YAML/JSON you may edit), `generated/` (untouched originals), `approval-diff.txt` (after approve), `installer/` (standard installer names), `run.json` (run state, hashes and approval), and, after build, `artifacts/`. `work/active-run.json` points to the active run. The testing phase writes `work/preflight-<time>.log` and `.json` outside any run.

`backups/<cluster>/<run-id>/` contains `inventory/`, `review/`, `generated/`, `approval-diff.txt`, `artifacts/`, `run.json`, `checksums.json`, and the newest `preflight-<time>.log` / `.json` found in `work/` when the archive ran (the testing phase's result; it may belong to an earlier run if you did not repeat the tests). The archive routine copies and SHA-256 verifies its payload before resetting the four active inventory files from `inventory_templates/` and the two testing files from `testing_templates/`. The original work directory is retained.

## Approval gate

`prepare` generates the YAML/JSON, keeps an untouched copy in `generated/` and records their hashes. You review (and may edit) the **cluster-prefixed files in `review/`**. `approve -e run_id=...` checks that the inventory is unchanged and that every file still passes the basic checks, copies the final `install-config.yaml` and `agent-config.yaml` to `installer/`, and records the SHA-256 of the files **as you approved them** (`approved_checksums` in `run.json`, plus `edited_files`). If you edited anything, the diff against `generated/` is printed (the `pullSecret` and `sshKey` lines are never shown) and saved as `approval-diff.txt`. `build` rechecks the approved hashes and refuses unapproved runs or files changed after approval. This is a command-line approval record, **not** a web interface or a cryptographic signature.

To correct the inventory after preparing, run `ansible-playbook playbooks/discard.yml -e run_id=<run-id>` and then prepare again. Discard only removes the active-run marker; it preserves the prior run workspace. Edit only the files in `review/`; the files in `installer/` are overwritten at approval.

## Security and recovery

The inventory snapshot and generated configuration may contain or reference sensitive material, including the pull secret, SSH public key, and any credentials embedded in proxy URLs. Use restricted permissions, encrypted backups, and a secure storage policy. The factory does not upload backups off-host, automatically prune them, or restore them. `archive` can fail partway through the inventory reset; check the inventory before starting a new run. Avoid concurrent runs in the same checkout.

QCOW2 format verification does **not** establish OCI import/boot compatibility. Test the generated image with the target OCI boot workflow.
