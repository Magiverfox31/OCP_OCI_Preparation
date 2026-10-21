# URL reachability preflight

The preflight checks, from the Oracle Linux 9 bastion, that the URLs OpenShift needs are reachable. It runs automatically at the start of `prepare` (before any run directory is created) and can be run alone:

```bash
ansible-playbook playbooks/preflight.yml
```

Bypass deliberately (for example, a disconnected install using a mirror registry): `ansible-playbook playbooks/prepare.yml -e skip_preflight=true --ask-become-pass`, or set `preflight.enabled: false` in the inventory.

## How a URL is judged

Each URL is probed with `curl -I` using the configured timeout, in parallel.

| Result | Meaning |
| --- | --- |
| `OK  HTTP <code>` | A server answered. **Any** HTTP status (200, 301, 401, 403, 404) counts as reachable. |
| `FAIL Could not resolve host` | DNS cannot resolve the name from the bastion. |
| `FAIL ... timed out` / `Failed to connect` | A firewall, proxy or route blocks the path. |
| `FAIL SSL certificate problem` | TLS interception or missing CA; set `preflight.ca_bundle`. |

If any URL fails, `prepare` stops with the list and no run is created.

## Configuration (`inventory/preflight.yml`)

| Field | Purpose |
| --- | --- |
| `enabled` | `false` skips the check. |
| `timeout_seconds` | Connect and total timeout per URL (default 10). |
| `proxy` | Optional proxy URL passed to curl. Empty uses curl's environment (`https_proxy` etc.). Independent of the cluster `proxy:` block in `network.yml`; set both if both paths need the proxy. |
| `ca_bundle` | Optional absolute path to a CA bundle for TLS-inspecting proxies. |
| `urls` | URLs to probe. Entries without a scheme are probed as `https://`. |

## Limits

- The shipped URL list is a starting point; **verify it against the Red Hat OpenShift 4.22 documentation** for your install method, proxy and mirror setup, and add any internal mirror or OCI endpoints you rely on.
- It tests the **bastion's** path only. The OpenShift nodes on OCI have their own subnets, NSGs, routes and proxy settings and must be checked separately.
- Reachability of a host is not proof that every path or port a component needs is allowed.
- Results are stored in `work/<cluster>/<run-id>/preflight-report.json` and archived with the run.
- DNS (Infoblox) and F5 BIG-IP checks are a separate stage (`netcheck`, see [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md)) with their own skip switch (`-e skip_netcheck=true`).
