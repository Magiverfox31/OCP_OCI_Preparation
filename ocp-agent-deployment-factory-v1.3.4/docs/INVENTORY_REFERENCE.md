# Inventory reference — v1.3.4

Edit **only** the four files in `inventory/`. The corresponding `inventory_templates/` files are the clean reset baseline; do not place real cluster values or secrets there.

| File | Required values |
| --- | --- |
| `cluster.yml` | DNS-label `name`, `base_domain`, `ocp_version` (4.22 family), `architecture: x86_64`, absolute `pull_secret_file`, `ssh_public_key_file`, control-plane `rendezvous_ip` |
| `nodes.yml` | Exactly three `master` hosts; any supported `worker` hosts; each has unique `name`, `ip`, `mac`, `interface`, `prefix_length`; optional per-host `gateway`, `dns_servers`, `boot_mac_address`, `root_device_hint`, `oci_vm_id` |
| `network.yml` | `machine_network`, `cluster_network`, `host_prefix`, `service_network`, `network_type: OVNKubernetes`, `dns_servers`, `gateway` |
| `infrastructure.yml` | `platform: oci`, `dns_provider: infoblox`, `loadbalancer_provider: f5`, `api_vip`, `ingress_vip`, `f5_self_ips` |

The current validation supports **OCI + Infoblox + F5, x86_64, OCP 4.22, exactly three masters**. It is not yet a general multi-platform/multi-version validator. The inventory may be reused for multiple *sequential* clusters; each completed run has a distinct cluster/run-ID archive.

Use full node data appropriate to your deployment. Example addresses in comments are illustrations only. The pull secret is loaded from its referenced file and embedded in the generated install configuration; protect it. The `release_image` field is present in the inventory, but confirm its actual effect in the Jinja2 template before relying on it. VM identifiers are metadata, not OCI provisioning instructions.

## Preflight scope

Current Python validation checks names, version family, CIDR syntax, IP/MAC syntax and uniqueness, master count, rendezvous IP, SSH public key prefix and pull-secret JSON. It does **not** prove that IPs are reachable, the NICs exist in OCI, F5 is correctly configured, Infoblox records exist, or that the generated manifests will be accepted by the target release. Validate these independently.
