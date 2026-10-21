# Dependency matrix

The controller is **Oracle Linux 9**. First install `python3` and `ansible-core` from approved repositories; Ansible cannot bootstrap itself. Then run:

```bash
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

The playbook uses DNF to ensure `curl`, `nmap-ncat` (`nc`), `nmstate` (`nmstatectl`), `qemu-img`, `bind-utils` (`dig`, `nslookup`), `iproute` (`ip`), `openssl`, `tar`, `gzip`, `python3`, `python3-pip`, `python3-pyyaml`, and `python3-jinja2` are installed. It verifies the main commands and Python `yaml` and `jinja2` imports.

The `openshift-install` binary is **not installed** by the playbook. Install the approved release-specific binary separately; the build stage checks the version string against inventory.

`curl` is used by the factory for the OCP allowlist URL preflight and the F5 REST audit, and `dig` (package `bind-utils`) for the Infoblox DNS checks (`prepare`/`preflight`/`netcheck`). The F5 TCP probe uses Python sockets. `nc` and `nmstatectl` are installed for manual diagnostics only. The factory does not run OCI network checks. Package availability depends on enabled Oracle Linux repositories. See [BASTION_PREREQUISITES.md](BASTION_PREREQUISITES.md).
