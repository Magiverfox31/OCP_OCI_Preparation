# Inventory reference — v1.7.0

Edit **only** the five files in `inventory/`. The corresponding `inventory_templates/` files are the clean reset baseline; do not place real cluster values or secrets there.

| File | Required values |
| --- | --- |
| `cluster.yml` | DNS-label `name`, `base_domain`, `ocp_version` (4.22 family), `architecture: x86_64`, absolute `pull_secret_file`, `ssh_public_key_file`, control-plane `rendezvous_ip` |
| `nodes.yml` | Exactly three `master` hosts; any supported `worker` hosts; each has unique `name`, `ip`, `mac`, `interface`, `prefix_length`; optional per-host `gateway`, `dns_servers`, `root_device_hint`, `oci_vm_id` |
| `network.yml` | `machine_network`, `cluster_network`, `host_prefix`, `service_network`, `network_type: OVNKubernetes`, `dns_servers`, `gateway`; optional `proxy` block (below) |
| `infrastructure.yml` | `platform: oci`, `dns_provider: infoblox`, `loadbalancer_provider: f5`, `api_vip`, `ingress_vip`, `f5_self_ips`; optional `dns_checks` and `f5_checks` blocks (see "DNS and F5 check settings") |
| `preflight.yml` | `enabled`, `timeout_seconds`, `http_client` (`auto`/`curl`/`urllib`), `proxy` (optional), `ca_bundle` (optional), `urls` (list). See [PREFLIGHT.md](PREFLIGHT.md) |

The current validation supports **OCI + Infoblox + F5, x86_64, OCP 4.22, exactly three masters**. It is not yet a general multi-platform/multi-version validator. The inventory may be reused for multiple *sequential* clusters; each completed run has a distinct cluster/run-ID archive.

Use full node data appropriate to your deployment. Example addresses in comments are illustrations only. The pull secret is loaded from its referenced file and embedded in the generated install configuration; protect it. `cluster.release_image` (optional) is passed to `openshift-install` at build time via `OPENSHIFT_INSTALL_RELEASE_IMAGE_OVERRIDE`; leave it empty to use the installer's built-in release. It does not add mirror/`imageContentSources` settings for disconnected installs. The install-config worker `replicas` is derived from the number of `worker` hosts in `nodes.yml`. VM identifiers are metadata, not OCI provisioning instructions. (`boot_mac_address`, listed in earlier versions, was never used and has been removed.)

## Networking and proxy sections of install-config.yaml

`install-config.yaml` always contains `networking.machineNetwork`, `networking.clusterNetwork` (`cluster_network` with `host_prefix`) and `networking.serviceNetwork` (`service_network`), taken from `network.yml`. Validation requires the three networks not to overlap and `host_prefix` to be larger than the cluster network prefix (at most 32). One CIDR per network (IPv4) is supported; dual-stack/IPv6 is not.

The optional `proxy:` block in `network.yml` renders the cluster-wide proxy:

| Field | Meaning |
| --- | --- |
| `enabled` | `false` (default) omits the proxy section completely. |
| `http_proxy`, `https_proxy` | Proxy URLs; at least one is required when enabled. Must start with `http://` (OpenShift supports only http proxy URLs). |
| `no_proxy` | Extra exclusions (list or comma string). The factory **always adds** `localhost`, `127.0.0.1`, `.svc`, `.cluster.local`, `api-int.<cluster>.<base_domain>` and the machine, cluster and service networks. Add your internal domain, Infoblox/F5/registry addresses, and any other destination that must bypass the proxy. |
| `additional_trust_bundle_file` | Optional absolute path to a PEM CA bundle, rendered as `additionalTrustBundle`. |
| `additional_trust_bundle_policy` | `Proxyonly` (default) or `Always`. Only rendered together with a trust bundle. |

The proxy section configures the cluster, not the bastion or the installer's own downloads. Proxy URLs containing credentials end up in the review files, the work directory and the backups; protect them like the pull secret. The preflight `proxy` setting is separate from this block.

## DNS and F5 check settings (`infrastructure.yml`)

These blocks configure the `netcheck` stage described in [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md). All have working defaults except the F5 REST credentials. **Quote string values such as `"warn"`/`"off"`**: YAML 1.1 reads an unquoted `off` as boolean false (the factory tolerates this for `tcp_probe`, but quoting is safest).

| Field | Default | Meaning |
| --- | --- | --- |
| `dns_checks.enabled` | `true` | Run the dig-based DNS checks against every resolver in `network.dns_servers` and per-node `dns_servers`. |
| `dns_checks.timeout_seconds` | `3` | Per-query timeout. |
| `dns_checks.node_domain` | `""` | Domain appended to node names that contain no dot. Empty = `<cluster>.<base_domain>`. |
| `dns_checks.api_int_vip` | `""` | Expected `api-int` address if it differs from `api_vip`. |
| `dns_checks.check_reverse` | `true` | Require a PTR record for every node IP. |
| `dns_checks.method` | `"auto"` | `"auto"` (dig if installed, otherwise the built-in Python resolver), `"dig"` or `"builtin"`. See [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md). |
| `dns_checks.transport` | `"auto"` | `"auto"` (UDP, then TCP when UDP gets no reply; a resolver that needs TCP gets a `WARN`), `"udp"` or `"tcp"`. |
| `f5_checks.enabled` | `true` | Master switch for the F5 checks. |
| `f5_checks.tcp_probe` | `"warn"` | `"off"`, `"warn"` (report only) or `"require"` (fail on any refused/timed-out probe). Use `"require"` only once the cluster is running. |
| `f5_checks.timeout_seconds` | `5` | TCP/REST timeout. |
| `f5_checks.rest.enabled` | `false` | Read-only iControl REST audit of virtual servers, pools and self IPs. |
| `f5_checks.rest.mgmt_url` | `""` | BIG-IP management URL; must start with `https://`. |
| `f5_checks.rest.username` | `""` | Read-only account name. |
| `f5_checks.rest.password_env` | `F5_PASSWORD` | Environment variable holding the password. **Never put the password in the inventory.** |
| `f5_checks.rest.password_file` | `""` | Alternative: absolute path to a file containing only the password (takes precedence over the variable). |
| `f5_checks.rest.verify_tls` | `true` | `false` disables certificate verification (last resort for a self-signed management certificate). |
| `f5_checks.rest.ca_bundle` | `""` | PEM CA bundle that signed the management certificate. |
| `f5_checks.rest.http_client` | `"auto"` | `"auto"` (curl if installed, otherwise the built-in Python client), `"curl"` or `"urllib"`. |

Validation also rejects an `api_vip` or `ingress_vip` equal to a node IP.

## Preflight scope

Current Python validation checks names, version family, CIDR syntax, IP/MAC syntax and uniqueness, master count, rendezvous IP, SSH public key prefix, pull-secret JSON the preflight block, the `dns_checks`/`f5_checks` settings and that VIPs are not node IPs. Syntax validation alone does **not** prove anything about the live environment. The separate `netcheck` stage queries DNS and (optionally) the BIG-IP, but only from the bastion; it does not prove that the NICs exist in OCI, that OCI security rules allow node traffic, or that the generated manifests will be accepted by the target release. Validate these independently.
