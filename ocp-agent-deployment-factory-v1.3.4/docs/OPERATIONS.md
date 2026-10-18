# Operator runbook — Oracle Linux 9

From the extracted project root, with approved DNF repositories and sudo rights:

```bash
sudo dnf install -y python3 ansible-core
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

Install an approved `openshift-install` binary matching the target OCP release separately and confirm `openshift-install version`. Ensure `python3 -c 'import yaml, jinja2'` succeeds.

1. Fill in the four `inventory/*.yml` files. Keep real pull secrets outside source control.
2. Run `ansible-playbook playbooks/prepare.yml --ask-become-pass`.
3. Read `work/<cluster>/<run-id>/review/<cluster>-install-config.yaml` and `<cluster>-agent-config.yaml`. Check addresses, host roles, MACs, CIDRs, pull-secret handling, and expected DNS/F5 endpoints. The current code does not create a separate validation report.
4. Run `ansible-playbook playbooks/approve.yml -e run_id=<run-id>` only after review.
5. Run `ansible-playbook playbooks/build.yml --ask-become-pass` to create ISO and QCOW2.
6. Validate the image against OCI import and boot requirements **before production use**.
7. Run `ansible-playbook playbooks/archive.yml` to copy/verify the backup and reset the active inventory.

For rejection: `ansible-playbook playbooks/discard.yml -e run_id=<run-id>`; update inventory and prepare again. An interrupted/failed build may need manual inspection of its working directory before retrying.

**Warning:** `archive` resets the active inventory after a verified archive; keep a second secure backup of critical inputs. One active run per checkout; parallel cluster builds require separate checkouts.

## Troubleshooting

- `dnf` fails: inspect `sudo dnf repolist`, repositories and proxy.
- Python import fails: check `python3-pyyaml` and `python3-jinja2` availability.
- Installer missing/mismatched: check `command -v openshift-install` and `openshift-install version`.
- Approval rejected: check whether inventory or review files changed; discard and re-prepare.
- ISO/QCOW2 failure: inspect the preserved `work/<cluster>/<run-id>/` and verify disk space, installer logs and `qemu-img info`.
- OCI boot failure: image format alone is insufficient; validate OCI image import/firmware requirements.

See [BASTION_PREREQUISITES.md](BASTION_PREREQUISITES.md), [INVENTORY_REFERENCE.md](INVENTORY_REFERENCE.md), [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md) and [ARTIFACTS_AND_BACKUPS.md](ARTIFACTS_AND_BACKUPS.md).
