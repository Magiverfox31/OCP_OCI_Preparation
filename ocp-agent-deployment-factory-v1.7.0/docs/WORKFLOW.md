# Deployment workflow and mandatory review gate

1. **Bootstrap dependencies**: `playbooks/dependencies.yml` runs explicitly or as part of prepare/build. Oracle Linux 9 only. Required packages must install; optional diagnostic tools (`curl`, `dig`, `nc`, ...) are tolerated when missing, because the checks fall back to built-in Python clients ([TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md)).
2. **Prepare**: `playbooks/prepare.yml` validates inventory, runs the **URL reachability preflight** (see [PREFLIGHT.md](PREFLIGHT.md)) and the **DNS (Infoblox) and F5 BIG-IP checks** (see [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md)); a failure in either stops the run before anything is created. It then validates the networks (no overlaps, valid `host_prefix`) and the optional proxy block, and generates the two configuration files. It creates a run ID, inventory snapshot, preflight and netcheck reports and hashes. Use `-e skip_preflight=true` or `-e skip_netcheck=true` to bypass either check deliberately. `playbooks/netcheck.yml` runs the DNS/F5 checks alone; run it before `archive`, which resets the inventory.
3. **Human review**: inspect the files under `work/<cluster>/<run-id>/review/`. No ISO is created at this stage.
4. **Approve**: `playbooks/approve.yml -e run_id=<run-id>` records approval only if review files and inventory still match their recorded hashes.
5. **Build**: `playbooks/build.yml` validates approval, checks `openshift-install`, creates the ISO (honouring `cluster.release_image` if set), converts it to QCOW2, and verifies QCOW2 format. A failed build can be retried: installer inputs are restored from the approved, hash-verified review files.
6. **Archive**: `playbooks/archive.yml` copies the inventory, YAML, preflight report, ISO and QCOW2 into `backups/<cluster>/<run-id>/`, verifies checksums, then resets active inventory from clean templates.
7. **Next cluster**: populate the fresh inventory and repeat.

To reject, use `playbooks/discard.yml -e run_id=<run-id>` and prepare again.

**Implementation boundaries:** The workflow supports one active run per checkout. OCI-side readiness (NSGs, routes, node-subnet DNS views) and OCI image bootability are not automated; the bastion URL preflight and the DNS/F5 checks are, but only from the bastion's point of view. Check results are stored as JSON per run. Consult [OPERATIONS.md](OPERATIONS.md) for exact commands.
