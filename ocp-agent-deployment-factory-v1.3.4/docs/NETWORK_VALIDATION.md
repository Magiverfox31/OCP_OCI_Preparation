# OCI / Infoblox / F5 external prerequisite checks

**These are manual checks, not automated live tests in v1.3.4.** The dependency playbook installs tools; it does not connect to Infoblox or F5 to verify their configuration.

## DNS

Use the DNS resolver IPs from `inventory/network.yml`:
```bash
dig @<dns-server-ip> api.<cluster>.<base-domain> A +short
dig @<dns-server-ip> api-int.<cluster>.<base-domain> A +short
dig @<dns-server-ip> test.apps.<cluster>.<base-domain> A +short
dig @<dns-server-ip> -x <node-ip> +short
```
Check forward and reverse records for the hosts and ensure the wildcard applications name resolves to the ingress VIP. A successful lookup alone does not prove routing or LB health.

## F5 and networking

Verify the F5 API and ingress VIPs and their pools/health monitors. F5 Self IPs are separate from virtual IPs. Example tests from a reachable test host:
```bash
nc -zvw3 <api-vip> 6443
nc -zvw3 <api-vip> 22623
nc -zvw3 <ingress-vip> 443
nc -zvw3 <ingress-vip> 80
ip route
```
Ports may not accept connections **before** the relevant OpenShift services are running. A failed early probe is not necessarily a misconfiguration. Validate pool membership, health checks, OCI NSGs/security lists, routes, interface addressing, MTU, DNS/NTP and registry/mirror connectivity with the infrastructure teams.

## Limitations

The factory does not provision OCI VMs, modify F5, create Infoblox records, or guarantee image bootability. Do not treat package installation or inventory syntax validation as evidence that these services are ready.
