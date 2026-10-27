# Tools, blocked tools and built-in fallbacks

Locked-down bastions often lack common network tools, block ICMP (ping), or allow only some ports. The factory is built so that a missing or blocked tool degrades gracefully instead of stopping the run.

## ICMP (ping) is never used

No stage sends ICMP. Reachability is always tested with a real TCP connection or a real application request (a DNS query, an HTTP request, a TCP connect to a VIP port). An unanswered ping proves little: ICMP is commonly blocked by firewalls and OCI security rules even when the service works. If you need a quick manual reachability test, see "Manual alternatives" below.

## What the factory uses, and what happens when it is missing

| Function | Preferred tool | Fallback when the tool is missing | Setting that overrides the choice |
| --- | --- | --- | --- |
| DNS queries (`netcheck`) | `dig` (package `bind-utils`) | Built-in Python DNS client | `dns_checks.method` (testing/dns_f5.yml): `auto` (default), `dig`, `builtin` |
| DNS when UDP/53 is blocked | n/a | `auto` retries over **TCP/53** per resolver and reports a `WARN` | `dns_checks.transport` (testing/dns_f5.yml): `auto` (default), `udp`, `tcp` |
| URL preflight (`prepare`, `preflight`) | `curl` | Built-in Python HTTP client | `preflight.http_client`: `auto` (default), `curl`, `urllib` |
| F5 REST audit (`netcheck`) | `curl` | Built-in Python HTTP client | `f5_checks.rest.http_client` (testing/dns_f5.yml): `auto` (default), `curl`, `urllib` |
| F5 VIP TCP probe | none needed | Always the Python socket library | `f5_checks.tcp_probe` (testing/dns_f5.yml) |
| Manual diagnostics (`nc`, `nslookup`, `ip`, `openssl`) | those tools | none: the factory does not call them | n/a |
| Build (`qemu-img`, `nmstatectl`, `python3`, PyYAML, Jinja2, `openshift-install`) | required | **none**: the run stops if these are missing | n/a |

`auto` means: use the preferred tool when it is installed, otherwise the built-in one. `dig`/`curl` (or `builtin`/`urllib`) force one choice; forcing a tool that is not installed stops with a clear message.

### Required and optional packages

`playbooks/dependencies.yml` installs **required** packages and stops if they cannot be installed: `python3`, `python3-pyyaml`, `python3-jinja2`, `qemu-img`, `nmstate`, `tar`, `gzip`. (`nmstatectl` is needed because `openshift-install` uses it to build the agent ISO with static networking; it is a documented Red Hat prerequisite.)

It also tries **optional** packages (`curl`, `bind-utils`, `nmap-ncat`, `iproute`, `openssl`, `python3-pip`). If a repository blocks one, the playbook continues and prints which optional tool is missing and what the factory will do instead.

### Seeing which tool ran

- Preflight: the summary line ends with `(client: curl)` or `(client: built-in Python HTTP client (curl not found))`.
- Netcheck: the first line is `NETCHECK tools: DNS via dig; F5 REST via curl` (or the built-in equivalents).
- The same information is stored in `work/preflight-<time>.json`.

## Differences between the built-in clients and the standard tools

Built-in DNS client:

- Queries exactly the servers in the inventory, over UDP then TCP. It does not read `/etc/resolv.conf`, apply search domains, validate DNSSEC, or use EDNS.
- Checks A records (and PTR for reverse lookups), as the `dig` path does. A CNAME in the answer chain is followed by the server and handled correctly.
- Replies with a different transaction ID or from another source address are ignored, like a real resolver.

Built-in HTTP client:

- Uses the same inventory settings (`proxy`, `ca_bundle`, `timeout_seconds`) and the standard `http_proxy`, `https_proxy` and `no_proxy` environment variables when `proxy` is empty.
- Supports `http://` proxy URLs (HTTPS through a proxy uses CONNECT), which is what OpenShift itself requires. Proxy URLs with embedded credentials and `https://` proxy URLs were not tested.
- Error wording follows curl (`Could not resolve host`, `Operation timed out`, `SSL certificate problem`, `Connection refused`), so the troubleshooting tables apply to both.
- Redirects are not followed with either client: any HTTP answer, including 301, means the server is reachable.

## Manual alternatives when a tool is blocked or missing

| Instead of | Use |
| --- | --- |
| `ping <host>` | A TCP connect to a port you know should be open: `nc -zvw3 <host> <port>`; without `nc`: `timeout 3 bash -c '</dev/tcp/<host>/<port>' && echo open`; without either: `python3 -c "import socket;socket.create_connection(('<host>',<port>),3);print('open')"` |
| `traceroute <host>` | `tracepath -n <host>` (UDP, no root); `traceroute -T -p <port> <host>` (TCP, usually needs root) |
| `dig @<server> <name>` | `nslookup <name> <server>`; `host <name> <server>`; `getent hosts <name>` (system resolver only, not a chosen server); or run `ansible-playbook playbooks/netcheck.yml`, which works without `dig` |
| `dig +tcp` (UDP/53 blocked) | `nslookup -vc <name> <server>` forces TCP; the factory does this automatically with `transport: auto` |
| `nc` | the `/dev/tcp` and `python3` forms above |
| `curl -I <url>` | `wget --spider -S <url>`; `python3 -c "import urllib.request as u;print(u.urlopen(u.Request('<url>',method='HEAD'),timeout=5).status)"` |
| TLS inspection with `openssl` | `curl -vI https://<host>` or `python3 -c "import ssl,socket;print(ssl.get_server_certificate(('<host>',443)))"` |
| `ip route` | `cat /proc/net/route` (hex) or `route -n` (package `net-tools`) |

## Limits and testing status

The built-in DNS client was tested against a mock DNS server that speaks the real wire protocol over UDP and TCP (compressed names, truncation, REFUSED, SERVFAIL, NXDOMAIN, wrong transaction ID, corrupt replies, silent UDP). The built-in HTTP client was tested against local HTTP/HTTPS servers, a forward proxy (plain and CONNECT) and a mock BIG-IP. **None of this was tested against a real Infoblox grid, a real BIG-IP, a real proxy or a real Oracle Linux 9 host with Python 3.9** (the code was only checked to parse as Python 3.9). Confirm behaviour on your bastion with `ansible-playbook playbooks/netcheck.yml` and `playbooks/preflight.yml` before relying on it.
