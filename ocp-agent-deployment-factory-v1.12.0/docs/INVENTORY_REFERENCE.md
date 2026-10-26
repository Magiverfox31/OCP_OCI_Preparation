# Inventory reference — v1.12.0

Edit **only** the four build files in `inventory/` and, for the testing phase, the two files in `testing/`. The corresponding `inventory_templates/` and `testing_templates/` files are the clean reset baselines; do not place real cluster values or secrets there.

| File | Required values |
| --- | --- |
| `cluster.yml` | DNS-label `name`, `base_domain`, `ocp_version` (4.22 family), `architecture: x86_64`, absolute `pull_secret_file`, `ssh_public_key_file`, control-plane `rendezvous_ip`; `minimal_iso` (standard value `true`), `release_image`; optional `mirror` block (disconnected install) and `image_build.proxy` (see "Disconnected install" and "Image-build proxy") |
| `nodes.yml` | `node_defaults` (shared `interface`, `root_device_hint`, optional `prefix_length`) and the host lists `masters` (exactly three) and `workers`. Per host only `name`, `ip`, `mac` are required; see "Node settings" below |
| `network.yml` | `machine_network`, `cluster_network`, `host_prefix`, `service_network`, `network_type: OVNKubernetes`, `dns_servers`, `gateway`, optional `ntp_servers`; optional `proxy` block (below) |
| `infrastructure.yml` | `platform: oci`, `dns_provider: infoblox`, `loadbalancer_provider: f5`, `api_vip`, `ingress_vip`, `f5_self_ips` (needed only when the F5 checks are on). The `dns_checks`/`f5_checks` blocks live in `testing/dns_f5.yml`; leaving them here is an error |
| `testing/urls.yml` | Testing phase: `preflight:` block with `enabled`, `timeout_seconds`, `http_client` (`auto`/`curl`/`urllib`), `proxy` (optional), `ca_bundle` (optional), `urls` (list). See [PREFLIGHT.md](PREFLIGHT.md) |
| `testing/dns_f5.yml` | Testing phase: `dns_checks:` and `f5_checks:` blocks (see "DNS and F5 check settings") |

The current validation supports **OCI + Infoblox + F5, x86_64, OCP 4.22, exactly three masters**. It is not yet a general multi-platform/multi-version validator. The inventory may be reused for multiple *sequential* clusters; each completed run has a distinct cluster/run-ID archive.

Use full node data appropriate to your deployment. Example addresses in comments are illustrations only. The pull secret is loaded from its referenced file and embedded in the generated install configuration; protect it. `cluster.release_image` (optional) is passed to `openshift-install` at build time via `OPENSHIFT_INSTALL_RELEASE_IMAGE_OVERRIDE`; leave it empty to use the installer's built-in release. It does not add mirror/`imageContentSources` settings for disconnected installs. The install-config worker `replicas` is derived from the number of `worker` hosts in `nodes.yml`. VM identifiers are metadata, not OCI provisioning instructions. (`boot_mac_address`, listed in earlier versions, was never used and has been removed.)

## Node settings (`nodes.yml`) and what is shared

Per host you type only **`name`, `ip`, `mac`**. The role comes from the list the host is in (`masters:` or `workers:`). Everything else is shared:

| Setting | Where it is set once | Notes |
| --- | --- | --- |
| NIC name | `node_defaults.interface` | Required unless set on each host (the blank template leaves it empty on purpose, so you must choose, for example `enp0s5` or `ens3`). Must match the interface name the OS sees on the OCI VM. |
| MTU | `node_defaults.mtu` | Standard value **9000**, rendered as `mtu:` on every host's interface. If the key is removed from both `node_defaults` and the host, 9000 is still used. Whole number 576-9216; override on one host by adding `mtu` to that host. 9000 requires jumbo-frame support along the whole network path. |
| Root disk | `node_defaults.root_device_hint` | For example `/dev/sda`. Empty means the installer chooses. Must start with `/dev/`. |
| Subnet prefix | derived from `network.machine_network` | Override with `node_defaults.prefix_length`. |
| Gateway | `network.gateway` | |
| DNS servers | `network.dns_servers` | |
| NTP servers | `network.ntp_servers` | Rendered once as `additionalNTPSources` in `agent-config.yaml` (cluster-wide, not per host). Empty omits the section. |

Any shared value can still be overridden on one host by adding the key to that host (allowed host keys: `name`, `ip`, `mac`, `interface`, `prefix_length`, `mtu`, `gateway`, `dns_servers`, `root_device_hint`, `oci_vm_id`). An unknown key (for example a typo such as `root_device_hints`) is rejected rather than silently ignored.

```yaml
node_defaults:
  interface: enp0s5
  root_device_hint: /dev/sda
  mtu: 9000                # standard value
masters:
  - {name: ocp-uat-cp-1, ip: 10.10.10.11, mac: "02:00:00:00:00:11"}
  - {name: ocp-uat-cp-2, ip: 10.10.10.12, mac: "02:00:00:00:00:12"}
  - {name: ocp-uat-cp-3, ip: 10.10.10.13, mac: "02:00:00:00:00:13"}
workers:
  - {name: ocp-uat-wk-1, ip: 10.10.10.14, mac: "02:00:00:00:00:14"}
  - {name: ocp-uat-wk-2, ip: 10.10.10.15, mac: "02:00:00:00:00:15", root_device_hint: /dev/nvme0n1}  # per-host override
```

A host `name` may be a short name or an FQDN such as `master01.<cluster>.<base_domain>`; it is written as the host's `hostname` exactly as given, and the DNS checks use a name that contains a dot as the record to look up.

The older format (a single `nodes:` list with `role:` on every host) is still accepted, and `node_defaults` also applies to it. Using `nodes:` together with `masters:`/`workers:` is rejected. Every node IP must lie inside `network.machine_network`.

## OCI image metadata (`templates/image_metadata.json`)

Not an inventory field. `templates/image_metadata.json` holds the OCI launch options (UEFI_64, PARAVIRTUALIZED volumes and network, `operatingSystem: Custom`). To change them, edit that file; it must stay valid JSON (prepare stops otherwise). Prepare copies it into the review folder as `<cluster>-image_metadata.json`, so it is hash-pinned and approved with the YAML; edits after prepare invalidate the approval.

## Minimal ISO (`cluster.minimal_iso`)

`minimal_iso` is written as `minimalISO:` in `agent-config.yaml` (always rendered, so the review file states the choice). The standard value is `true`; if the key is missing from `cluster.yml`, `true` is used.

| Value | Effect |
| --- | --- |
| `false` | Full ISO that contains the RHCOS rootfs. Larger; works without outside access at boot. |
| `true` (standard value) | ISO **without** the rootfs image; it is retrieved during installation. Smaller image, but every node must be able to download the rootfs, so the **node subnet** (not just the bastion) needs access to the Red Hat default rootfs URL. In restricted networks the installer offers `bootArtifactsBaseURL` to point at an internal web server; the factory does not set it. |

Write the value as `true` or `false` without quotes; a quoted string is rejected.

## Disconnected install (`cluster.mirror`)

Set `mirror.enabled: true` when the cluster installs from an internal mirror registry (populated with `oc-mirror` or `oc adm release mirror`) instead of pulling from quay.io / registry.redhat.io.

| Field | Meaning |
| --- | --- |
| `mirror.enabled` | `true` adds the mirror settings to `install-config.yaml`. Default `false` (connected install). |
| `mirror.registry` | The mirrored repository as `host[:port]/path`, no `https://`, for example `registry.example.internal:8443/ocp4/openshift4`. |
| `mirror.sources` | Upstream repositories that are mirrored. Default: `quay.io/openshift-release-dev/ocp-release` and `quay.io/openshift-release-dev/ocp-v4.0-art-dev`. Each becomes one entry pointing at `mirror.registry`. |
| `mirror.sources_key` | `imageContentSources` (default, the field Red Hat's 4.22 agent-based installer documentation uses) or `imageDigestSources` (the newer name of the same setting). |
| `mirror.ca_bundle_file` | Absolute path to the PEM CA that signed the registry certificate. It is written to `additionalTrustBundle` (joined with the proxy CA when both exist) and, when present, `additionalTrustBundlePolicy` is set to `Always`, so it works without a proxy. |

When a mirror is enabled: the mirror host is added to `noProxy` automatically if the proxy is on; `prepare` prints a note if `cluster.release_image` is empty (set it to the mirrored release image for a fully disconnected build); the testing phase tests the registry (`https://<host:port>/v2/`) instead of the public URL list (see [PREFLIGHT.md](PREFLIGHT.md)). The pull secret must contain credentials for the mirror registry. The factory does not mirror images for you.

## Image-build proxy (`cluster.image_build.proxy`)

Controls the proxy variables `openshift-install` sees during the image build (phase 3). It does not affect the cluster proxy in `install-config.yaml` (that is `proxy.enabled` in `network.yml`).

| Value | Effect |
| --- | --- |
| `inherit` (default) | The factory leaves your shell environment unchanged. |
| `cluster` | Sets `http_proxy`, `https_proxy` and `no_proxy` (both cases) from `network.yml` `proxy`; requires `proxy.enabled: true`. |
| `none` | Removes `http_proxy`, `https_proxy`, `no_proxy` and `all_proxy` (any case) for the build, even if your shell has them set. |

The build prints which mode it used.

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

## Mirror test settings (`testing/urls.yml`)

| Key | Meaning |
| --- | --- |
| `urls_when_mirror` | URLs tested instead of `urls` when `cluster.mirror.enabled` is true. Default `[]`. |
| `mirror_probe_via_proxy` | `false` (default): the registry is tested directly; `true`: through the proxy. |

## DNS and F5 check settings (`testing/dns_f5.yml`)

These blocks sit at the top level of `testing/dns_f5.yml` (not under `infrastructure:`) and configure the DNS/F5 part of the testing phase described in [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md). All have working defaults except the F5 REST credentials. **Quote string values such as `"warn"`/`"off"`**: YAML 1.1 reads an unquoted `off` as boolean false (the factory tolerates this for `tcp_probe`, but quoting is safest).

| Field | Default | Meaning |
| --- | --- | --- |
| `dns_checks.enabled` | `true` | Run the dig-based DNS checks against every resolver in `network.dns_servers` and per-node `dns_servers`. |
| `dns_checks.timeout_seconds` | `3` | Per-query timeout. |
| `dns_checks.node_domain` | `""` | Domain appended to node names that contain no dot. Empty = `<cluster>.<base_domain>`. |
| `dns_checks.api_int_vip` | `""` | Expected `api-int` address if it differs from `api_vip`. |
| `dns_checks.check_reverse` | `true` | Require a PTR record for every node IP. |
| `dns_checks.method` | `"auto"` | `"auto"` (dig if installed, otherwise the built-in Python resolver), `"dig"` or `"builtin"`. See [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md). |
| `dns_checks.transport` | `"auto"` | `"auto"` (UDP, then TCP when UDP gets no reply; a resolver that needs TCP gets a `WARN`), `"udp"` or `"tcp"`. |
| `f5_checks.enabled` | `false` | Master switch for the F5 checks (TCP probe and REST audit). Off by default; when `true`, `f5_self_ips` must be a non-empty list of BIG-IP self IPs. |
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

Current Python validation checks names, version family, CIDR syntax, IP/MAC syntax and uniqueness, that each node IP is inside `machine_network`, host keys, `root_device_hint` format, `ntp_servers` entries, master count, rendezvous IP, SSH public key prefix, and pull-secret JSON. The testing-phase settings (the `testing/urls.yml` block, `dns_checks`/`f5_checks`) and the check that VIPs are not node IPs are validated only by the testing phase, never by `prepare`. Syntax validation alone does **not** prove anything about the live environment. The separate `netcheck` stage queries DNS and (optionally) the BIG-IP, but only from the bastion; it does not prove that the NICs exist in OCI, that OCI security rules allow node traffic, or that the generated manifests will be accepted by the target release. Validate these independently.
