# Dependency matrix

The controller is **Oracle Linux 9**. First install `python3` and `ansible-core` from approved repositories; Ansible cannot bootstrap itself. Then run:

```bash
ansible-playbook playbooks/dependencies.yml --ask-become-pass
```

The playbook installs two tiers with DNF:

| Tier | Packages | If it cannot be installed |
| --- | --- | --- |
| **Required** | `python3`, `python3-pyyaml`, `python3-jinja2`, `qemu-img`, `nmstate` (`nmstatectl`), `tar`, `gzip` | The run stops. The build cannot work without them. |
| **Optional** | `curl`, `bind-utils` (`dig`, `nslookup`), `nmap-ncat` (`nc`), `iproute` (`ip`), `openssl`, `python3-pip` | The playbook continues and prints what the factory will do instead (see [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md)). |

It verifies `qemu-img`, `nmstatectl` and the Python `yaml`/`jinja2` imports, then reports which optional commands are missing. `nmstatectl` is required because `openshift-install agent create image` uses it for static host networking (a documented Red Hat prerequisite).

The `openshift-install` binary is **not installed** by the playbook. Install the approved release-specific binary separately; the build stage checks the version string against inventory.

`curl` is used for the OCP allowlist URL preflight and the F5 REST audit, and `dig` (package `bind-utils`) for the Infoblox DNS checks, **when installed**; otherwise built-in Python clients do the same work. The F5 TCP probe always uses Python sockets. `nc`, `nslookup`, `ip` and `openssl` are installed for manual diagnostics only. The factory does not run OCI network checks. Package availability depends on enabled Oracle Linux repositories. See [BASTION_PREREQUISITES.md](BASTION_PREREQUISITES.md).
