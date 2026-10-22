# Full preflight and URL reachability

## The full preflight (`playbooks/preflight.yml`)

`ansible-playbook playbooks/preflight.yml` runs **every** check and does not stop at the first failure:

1. **Inventory**: all five files are loaded and validated; every problem is listed, each naming the file, the field and the rejected value (the older behaviour stopped at the first one).
2. **Tools**: `openshift-install` (and that its version matches `cluster.ocp_version`), `qemu-img`, `nmstatectl` are required (FAIL when missing); `tar`, `curl`, `dig`, `nc` are optional (WARN).
3. **URLs**: every URL in `inventory/preflight.yml`, one PASS or FAIL line each.
4. **DNS**: the Infoblox checks (see [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md)).
5. **F5**: only when `infrastructure.f5_checks.enabled` is true. It is **false by default**, so F5 is ignored.

In a terminal the report is coloured: `PASS` green, `FAIL` red, `WARN` yellow (and the FAILED list, the counts and the `RESULT:` line likewise). The playbook writes the coloured report straight to the terminal; when there is no terminal (cron, CI, output redirected away) it shows a plain copy instead. The saved `.log` file is always plain text, so it is safe to open or attach anywhere. Running the script directly, `python3 scripts/factory.py preflight --color` gives the same colours.

The output ends with a summary (`PASSED / WARNINGS / FAILED` counts, then the list of failures and warnings and a `RESULT:` line). The same text is saved as `work/preflight-<UTC time>.log`, with a machine-readable `work/preflight-<UTC time>.json` beside it. The playbook fails at the end when anything failed. A check that cannot run because an inventory file is unreadable is reported as failed with the reason.

`prepare` still stops at its first failing stage (inventory, then URLs, then DNS) because it must not create files from a bad inventory; use this full preflight first to see everything at once.

## URL reachability (the part `prepare` runs)

The preflight checks, from the Oracle Linux 9 bastion, that the URLs OpenShift needs are reachable. It runs automatically at the start of `prepare` (before any run directory is created) and is part of the full preflight above:

Bypass deliberately (for example, a disconnected install using a mirror registry): `ansible-playbook playbooks/prepare.yml -e skip_preflight=true --ask-become-pass`, or set `preflight.enabled: false` in the inventory.

## How a URL is judged

Each URL is probed with a HEAD request using the configured timeout, in parallel, with `curl` when installed and otherwise with a built-in Python HTTP client (see [TOOLS_AND_FALLBACKS.md](TOOLS_AND_FALLBACKS.md)). Redirects are not followed: any HTTP answer, including 301, means the server is reachable.

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
| `http_client` | `auto` (default: curl if installed, otherwise the built-in client), `curl` or `urllib`. The summary line shows which one ran. |
| `proxy` | Optional proxy URL (`http://...`) used by either client. Empty uses the environment (`https_proxy`, `no_proxy` etc.). Independent of the cluster `proxy:` block in `network.yml`; set both if both paths need the proxy. |
| `ca_bundle` | Optional absolute path to a CA bundle for TLS-inspecting proxies. |
| `urls` | URLs to probe. Entries without a scheme are probed as `https://`. |

## Limits

- The shipped URL list is a starting point; **verify it against the Red Hat OpenShift 4.22 documentation** for your install method, proxy and mirror setup, and add any internal mirror or OCI endpoints you rely on.
- It tests the **bastion's** path only. The OpenShift nodes on OCI have their own subnets, NSGs, routes and proxy settings and must be checked separately.
- Reachability of a host is not proof that every path or port a component needs is allowed.
- Results are stored in `work/<cluster>/<run-id>/preflight-report.json` and archived with the run.
- DNS (Infoblox) and F5 BIG-IP checks are a separate stage (`netcheck`, see [NETWORK_VALIDATION.md](NETWORK_VALIDATION.md)) with their own skip switch (`-e skip_netcheck=true`).
