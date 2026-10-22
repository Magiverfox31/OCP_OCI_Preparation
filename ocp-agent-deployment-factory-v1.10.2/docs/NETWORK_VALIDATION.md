# DNS (Infoblox) and F5 BIG-IP checks

The `netcheck` stage tests the DNS and load balancer prerequisites from the Oracle Linux 9 bastion. It is **read-only** (it never creates records or changes the BIG-IP).

- It runs automatically in `playbooks/prepare.yml`, after the URL preflight ([PREFLIGHT.md](PREFLIGHT.md)) and before any run directory is created.
- Run it alone with `ansible-playbook playbooks/netcheck.yml`. Do this **before `archive`**, because archive resets the inventory the checks read.
- Configure it in `inventory/infrastructure.yml` (`dns_checks`, `f5_checks`; field list in [INVENTORY_REFERENCE.md](INVENTORY_REFERENCE.md)).
- Bypass deliberately with `-e skip_netcheck=true`.
- Results are stored in `work/<cluster>/<run-id>/netcheck-report.json` (no credentials) and archived with the run.

| Status | Meaning |
| --- | --- |
| `OK` | The expectation was met. |
| `WARN` | Reported, never blocks (for example an extra pool member). Read these. |
| `FAIL` | Blocks `prepare`: no run is created until fixed or deliberately skipped. |

## DNS (Infoblox)

The checks query **every resolver** in `network.dns_servers` and any per-node `dns_servers`, i.e. the servers the nodes will use. They use `dig` when installed and otherwise a built-in Python DNS client (`dns_checks.method`), and they never use ping. If UDP/53 gets no reply but TCP/53 works, the resolver is checked over TCP and reported once as a `WARN` (`dns_checks.transport`). See [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md). Infoblox NIOS is a standard DNS server, so no Infoblox API access or credentials are needed.

| Record queried | Expected |
| --- | --- |
| `api.<cluster>.<base_domain>` A | `api_vip` |
| `api-int.<cluster>.<base_domain>` A | `api_vip` (or `dns_checks.api_int_vip`) |
| `preflight-<random>.apps.<cluster>.<base_domain>` A | `ingress_vip`. A random label proves the `*.apps` wildcard record exists rather than one specific name. |
| each node name, forward A | the node's `ip`. A name without a dot gets `dns_checks.node_domain` appended (default `<cluster>.<base_domain>`). |
| each node IP, reverse PTR | the node's FQDN. A missing PTR is `FAIL`; a different name is `WARN`. Skip with `check_reverse: false`. |

How failures read and what they usually mean:

| Result | Typical cause |
| --- | --- |
| `REFUSED` | The Infoblox allow-query ACL or view does not include the bastion's address (the nodes' subnet may be allowed while the bastion is not). A refusing or silent resolver is reported **once**, and its records are not checked. |
| `NXDOMAIN` | The record does not exist. Create the A record, the wildcard A record `*.apps.<cluster>.<base_domain>`, and PTR records for the nodes. |
| `got X, expected Y` | A record exists but points elsewhere (often a stale or mistyped VIP). |
| `SERVFAIL` | Zone not loaded or served, forwarder or DNSSEC problem on the resolver. |
| `no reply from server` | Routing, firewall or NSG blocks DNS between the bastion and the resolver. When both transports fail the message names each (`UDP: ...; TCP: ...`). |

Limits: the check shows what the resolver answers **to the bastion**. If Infoblox uses different views or ACLs for the node subnet, answers there can differ; verify from the node subnet too. Negative answers may be cached by the resolver. The check does not read Infoblox configuration (no WAPI), so it cannot say why a record is missing.

## F5 BIG-IP

**F5 checks are off by default** (`f5_checks.enabled: false`) and are skipped by preflight, netcheck and prepare. Set it to `true` to use the two checks below; `f5_self_ips` is then required.

Two independent checks, both under `f5_checks`.

### 1. REST configuration audit (`f5_checks.rest`, recommended before install)

Reads the BIG-IP over iControl REST (with `curl` when installed, otherwise a built-in Python HTTP client: `rest.http_client`) with three GET requests (`/mgmt/tm/ltm/virtual`, `/mgmt/tm/ltm/pool`, `/mgmt/tm/net/self`) and compares the result with the inventory.

| Virtual server destination | Its default pool must contain |
| --- | --- |
| `api_vip`:6443 | all master IPs |
| `api_vip`:22623 (machine config server) | all master IPs |
| `ingress_vip`:443 and :80 | all worker IPs (the masters when no workers are defined) |

| Result | Condition |
| --- | --- |
| `FAIL` | no virtual server with that address and port; virtual server disabled; no default pool; pool not found; an expected node missing from the pool; REST connection, TLS or credential error. |
| `WARN` | extra pool members not in the inventory; member port different from the VIP port; no pool-level health monitor (check member-level monitors manually); an inventory `f5_self_ips` address not found as a self IP (SNAT pool or floating addresses are not self IPs). |

Setup:

1. Create a **read-only** BIG-IP account that can read LTM virtual servers, pools and self IPs (an auditor-type role; verify the role on your BIG-IP version). An HTTP 403 means the role cannot read an object.
2. Set `f5_checks.rest.enabled: true`, `mgmt_url: "https://<management address>"` and `username`.
3. Provide the password outside the inventory: `export F5_PASSWORD='...'` (or set `password_env` to another variable name, or `password_file` to a file containing only the password). It is passed to curl on standard input, so it does not appear in the process list, and it is never written to a report.
4. Trust the management certificate with `ca_bundle: "/path/ca.pem"`. As a last resort set `verify_tls: false` (this disables certificate checking).
5. If the bastion has `https_proxy` set in its environment, add the BIG-IP management address to `no_proxy`, otherwise the REST requests go through the proxy.

Not checked: health monitor type or receive strings, TCP vs. fastL4 profiles, SNAT/source translation, iRules and local traffic policies, HA sync and traffic groups, live availability state, and route-domain or partition rules beyond matching the address and port. Review these manually.

### 2. TCP probe (`f5_checks.tcp_probe`)

Connects from the bastion to `api_vip`:6443, `api_vip`:22623, `ingress_vip`:443 and `ingress_vip`:80.

| Mode | Behaviour |
| --- | --- |
| `"off"` | No probe. |
| `"warn"` (default) | Reports each result; a refused or timed-out connection is a `WARN` and does not block. |
| `"require"` | A refused or timed-out connection is a `FAIL`. Use only once the cluster is running (run `netcheck.yml` before `archive`). |

Reading the result: `connection accepted` means something is listening. `refused` means the address answered but nothing accepted the connection; `timed out` means no answer at all (routing, firewall/NSG, or nothing listening). Before the cluster runs there is nothing behind the VIPs, so refused or timed-out results are expected and are not proof of a mistake. This is why the default is `warn`.

## Manual checks still recommended

These are outside what the factory can see; confirm them with the infrastructure teams (and against the Red Hat OpenShift 4.22 load-balancer requirements):

- BIG-IP health monitors suit each service, and TLS is **not terminated** on 6443 and 22623 (Layer 4 pass-through).
- BIG-IP self IPs (the source of health monitor traffic) are allowed to the nodes by OCI NSGs/security lists, and node subnets can reach the VIPs.
- Routes, MTU, NTP and registry/mirror reachability **from the node subnet** (not just the bastion).
- If `cluster.minimal_iso` is `true`, the nodes download the RHCOS rootfs at boot: confirm the node subnet can reach the Red Hat rootfs URL (or your internal mirror if you use `bootArtifactsBaseURL`). The bastion preflight list includes `rhcos.mirror.openshift.com`, but verify the exact host against the Red Hat documentation for your release.

Equivalent manual commands (alternatives when `dig`, `nc` or ping are blocked or missing are in [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md)):

```bash
dig @<dns-server-ip> api.<cluster>.<base-domain> A +short
dig @<dns-server-ip> api-int.<cluster>.<base-domain> A +short
dig @<dns-server-ip> test.apps.<cluster>.<base-domain> A +short
dig @<dns-server-ip> -x <node-ip> +short
nc -zvw3 <api-vip> 6443
nc -zvw3 <api-vip> 22623
nc -zvw3 <ingress-vip> 443
nc -zvw3 <ingress-vip> 80
```

## Testing status and limitations

The DNS logic was tested with the built-in resolver against a mock DNS server that speaks the real wire protocol over UDP and TCP, and with the `dig` path against a stub that reproduces dig's output format. The F5 logic was tested against a TLS mock of the iControl REST API, through both HTTP clients. **None of it was tested against a real `dig`, Infoblox grid or BIG-IP.** The REST parsing relies on documented field names (`destination`, `pool`, `membersReference`, `address`); if your BIG-IP version differs, a `FAIL` may reflect parsing rather than configuration, so confirm it manually and report it. The factory does not provision OCI VMs, create Infoblox records, modify the BIG-IP, or guarantee image bootability.
