"""DNS (Infoblox) and load balancer (F5 BIG-IP) readiness checks for the OpenShift agent factory.

Checks are read-only:
  * DNS:  `dig` queries against the resolvers listed in the inventory (what the nodes will use).
  * F5:   optional iControl REST read of virtual servers, pools and self IPs, plus optional TCP probes.
Statuses: OK, WARN (reported, never blocks), FAIL (blocks `prepare`).
"""
import concurrent.futures
import datetime
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

SERVICES = (  # (vip key, port, label, backend role)
    ('api_vip', 6443, 'API', 'masters'),
    ('api_vip', 22623, 'MCS', 'masters'),
    ('ingress_vip', 443, 'ingress-https', 'ingress'),
    ('ingress_vip', 80, 'ingress-http', 'ingress'),
)


class CheckError(RuntimeError):
    pass


def _r(category, name, status, detail=''):
    return {'category': category, 'name': name, 'status': status, 'detail': detail}


# ----------------------------------------------------------------------------- configuration
def dns_cfg(v):
    d = dict(enabled=True, timeout_seconds=3, node_domain='', api_int_vip='', check_reverse=True)
    d.update(v.get('infrastructure', {}).get('dns_checks') or {})
    return d


def f5_cfg(v):
    f = dict(enabled=True, tcp_probe='warn', timeout_seconds=5)
    f.update(v.get('infrastructure', {}).get('f5_checks') or {})
    if f['tcp_probe'] is False:  # YAML 1.1 reads an unquoted `off` as boolean false
        f['tcp_probe'] = 'off'
    rest = dict(enabled=False, mgmt_url='', username='', password_env='F5_PASSWORD',
                password_file='', verify_tls=True, ca_bundle='')
    rest.update(f.get('rest') or {})
    f['rest'] = rest
    return f


def validate_config(v):
    """Raise CheckError for an unusable configuration. Called from factory validation."""
    i = v['infrastructure']
    d, f = dns_cfg(v), f5_cfg(v)
    if d['enabled']:
        if int(d['timeout_seconds']) < 1:
            raise CheckError('infrastructure.dns_checks.timeout_seconds must be >= 1')
        if d['api_int_vip']:
            ipaddress.ip_address(d['api_int_vip'])
    if f['enabled']:
        if f['tcp_probe'] not in ('off', 'warn', 'require'):
            raise CheckError('infrastructure.f5_checks.tcp_probe must be off, warn or require')
        if int(f['timeout_seconds']) < 1:
            raise CheckError('infrastructure.f5_checks.timeout_seconds must be >= 1')
        rest = f['rest']
        if rest['enabled']:
            if not str(rest['mgmt_url']).startswith('https://'):
                raise CheckError('infrastructure.f5_checks.rest.mgmt_url must start with https://')
            if not rest['username']:
                raise CheckError('infrastructure.f5_checks.rest.username is required when rest.enabled is true')
            if rest['password_file'] and not Path(rest['password_file']).is_file():
                raise CheckError(f"Missing infrastructure.f5_checks.rest.password_file: {rest['password_file']}")
            if rest['ca_bundle'] and not Path(rest['ca_bundle']).is_file():
                raise CheckError(f"Missing infrastructure.f5_checks.rest.ca_bundle: {rest['ca_bundle']}")
    node_ips = {x['ip'] for x in v['nodes']}
    for k in ('api_vip', 'ingress_vip'):
        if i[k] in node_ips:
            raise CheckError(f'infrastructure.{k} {i[k]} is also a node IP; a VIP must be a separate address')


def _f5_password(rest, environ):
    if rest['password_file']:
        return Path(rest['password_file']).read_text().strip()
    pw = environ.get(rest['password_env'] or 'F5_PASSWORD', '')
    if not pw:
        raise CheckError(f"F5 REST password not found: set environment variable {rest['password_env'] or 'F5_PASSWORD'} "
                         'or infrastructure.f5_checks.rest.password_file (never put the password in the inventory)')
    return pw


# ----------------------------------------------------------------------------- DNS (Infoblox)
def _dig(dig, server, name, rtype, timeout, reverse=False):
    cmd = [dig, '+noall', '+comments', '+answer', f'+time={timeout}', '+tries=1', f'@{server}']
    cmd += ['-x', name] if reverse else [name, rtype]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 3 + 10)
    out = p.stdout
    if p.returncode != 0:
        if p.returncode == 9:
            return {'error': 'no reply from server (timeout, routing or firewall)'}
        return {'error': (p.stderr.strip() or out.strip() or f'dig exit code {p.returncode}')[:200]}
    m = re.search(r'status:\s*([A-Z]+)', out)
    status = m.group(1) if m else 'UNKNOWN'
    answers = []
    for line in out.splitlines():
        if not line.strip() or line.startswith(';'):
            continue
        parts = line.split()
        if len(parts) >= 5:
            answers.append((parts[3].upper(), parts[4].rstrip('.').lower() if parts[3].upper() in ('PTR', 'CNAME') else parts[4]))
    return {'status': status, 'answers': answers}


def _dns_problem(res):
    """Return an explanatory FAIL detail for a non-NOERROR/empty answer, or None."""
    if 'error' in res:
        return res['error']
    st = res['status']
    if st == 'REFUSED':
        return ('REFUSED: the Infoblox DNS server refuses queries from this host; check the '
                'allow-query ACL / views for the bastion address')
    if st == 'NXDOMAIN':
        return 'NXDOMAIN: record does not exist'
    if st == 'SERVFAIL':
        return 'SERVFAIL: server error (zone not loaded, forwarder problem or DNSSEC failure)'
    if st != 'NOERROR':
        return f'unexpected DNS status {st}'
    return None


def dns_checks(v, environ=None):
    d = dns_cfg(v)
    if not d['enabled']:
        return []
    dig = shutil.which('dig')
    if not dig:
        raise CheckError('dig not found in PATH; run playbooks/dependencies.yml (package bind-utils)')
    c, n, i, nodes = v['cluster'], v['network'], v['infrastructure'], v['nodes']
    cl, bd = c['name'], c['base_domain']
    timeout = int(d['timeout_seconds'])
    node_domain = d['node_domain'] or f'{cl}.{bd}'
    servers = list(dict.fromkeys(list(n['dns_servers']) + [s for x in nodes for s in (x.get('dns_servers') or [])]))
    api_int = d['api_int_vip'] or i['api_vip']
    wildcard = f"preflight-{os.urandom(3).hex()}.apps.{cl}.{bd}"

    tests = [('A', f'api.{cl}.{bd}', {i['api_vip']}, 'api record', False),
             ('A', f'api-int.{cl}.{bd}', {api_int}, 'api-int record', False),
             ('A', wildcard, {i['ingress_vip']}, '*.apps wildcard', False)]
    for x in nodes:
        fqdn = x['name'] if '.' in x['name'] else f"{x['name']}.{node_domain}"
        tests.append(('A', fqdn, {x['ip']}, f"node {x['name']} forward", False))
        if d['check_reverse']:
            tests.append(('PTR', x['ip'], {fqdn.lower()}, f"node {x['name']} reverse", True))

    def run(job):
        server, (rtype, name, expect, label, reverse) = job
        res = _dig(dig, server, name, rtype, timeout, reverse)
        title = f'{label}: {name} @{server}'
        problem = _dns_problem(res)
        if problem:
            return _r('dns', title, 'FAIL', problem)
        got = {val for t, val in res['answers'] if t == rtype}
        if not got:
            return _r('dns', title, 'FAIL', 'no %s record in the answer (expected %s)' % (rtype, ', '.join(sorted(expect))))
        if expect <= got:
            extra = got - expect
            if extra:
                return _r('dns', title, 'WARN', f"returns expected {', '.join(sorted(expect))} but also {', '.join(sorted(extra))}")
            return _r('dns', title, 'OK', ', '.join(sorted(got)))
        if rtype == 'PTR':
            return _r('dns', title, 'WARN', f"reverse name is {', '.join(sorted(got))}, expected {', '.join(sorted(expect))}")
        return _r('dns', title, 'FAIL', f"got {', '.join(sorted(got))}, expected {', '.join(sorted(expect))}")

    # Probe each resolver once first: a resolver that does not answer or refuses us is reported once, not per record.
    def usable(server):
        res = _dig(dig, server, f'api.{cl}.{bd}', 'A', timeout)
        if 'error' in res or res['status'] in ('REFUSED', 'SERVFAIL'):
            return server, _dns_problem(res)
        return server, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        probed = list(ex.map(usable, servers))
        results = [_r('dns', f'resolver @{srv}', 'FAIL', f'unusable, its records were not checked: {why}') for srv, why in probed if why]
        good = [srv for srv, why in probed if not why]
        results += list(ex.map(run, [(srv, t) for srv in good for t in tests]))
    return results


# ----------------------------------------------------------------------------- F5 BIG-IP
def _curl_cfg_quote(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _f5_get(curl, rest, password, path, timeout):
    base = rest['mgmt_url'].rstrip('/')
    cmd = [curl, '-sS', '--max-time', str(timeout), '-K', '-', '-H', 'Accept: application/json',
           '-w', '\n%{http_code}', base + path]
    if not rest['verify_tls']:
        cmd.insert(1, '-k')
    if rest['ca_bundle']:
        cmd[1:1] = ['--cacert', rest['ca_bundle']]
    cfg = 'user = "%s:%s"\n' % (_curl_cfg_quote(rest['username']), _curl_cfg_quote(password))  # via stdin: not visible in ps
    p = subprocess.run(cmd, input=cfg, capture_output=True, text=True)
    if p.returncode != 0:
        hint = ' (set f5_checks.rest.ca_bundle to the CA that signed the management certificate, or verify_tls: false as a last resort)' if p.returncode in (35, 51, 58, 60, 77, 83) else ''
        raise CheckError('cannot reach the BIG-IP management API: ' + (p.stderr.strip() or f'curl exit {p.returncode}')[:200] + hint)
    body, _, code = p.stdout.rpartition('\n')
    if code == '401':
        raise CheckError('BIG-IP rejected the credentials (HTTP 401)')
    if code == '403':
        raise CheckError('BIG-IP denied access to %s (HTTP 403); the account role cannot read this object' % path.split('?')[0])
    if code != '200':
        raise CheckError(f'BIG-IP returned HTTP {code} for {path.split("?")[0]}')
    try:
        return json.loads(body)
    except ValueError:
        raise CheckError(f'BIG-IP returned non-JSON for {path.split("?")[0]}')


def _strip_rd(addr):
    return addr.split('%')[0].split('/')[0]


def _vs_endpoint(dest):
    m = re.search(r'/([0-9a-fA-F.:]+?)(?:%\d+)?[:.](\d+)$', dest or '')
    return (m.group(1), int(m.group(2))) if m else (None, None)


def f5_rest_checks(v, environ):
    f = f5_cfg(v)
    rest = f['rest']
    if not (f['enabled'] and rest['enabled']):
        return []
    curl = shutil.which('curl')
    if not curl:
        raise CheckError('curl not found in PATH; run playbooks/dependencies.yml')
    password = _f5_password(rest, environ)
    t = int(f['timeout_seconds']) * 2
    i, nodes = v['infrastructure'], v['nodes']
    masters = {x['ip'] for x in nodes if x['role'] == 'master'}
    workers = {x['ip'] for x in nodes if x['role'] == 'worker'}
    try:
        vs_items = _f5_get(curl, rest, password, '/mgmt/tm/ltm/virtual?expandSubcollections=true', t).get('items', [])
        pool_items = _f5_get(curl, rest, password, '/mgmt/tm/ltm/pool?expandSubcollections=true', t).get('items', [])
        self_items = _f5_get(curl, rest, password, '/mgmt/tm/net/self', t).get('items', [])
    except CheckError as e:
        return [_r('f5-config', 'BIG-IP iControl REST', 'FAIL', str(e))]

    results = [_r('f5-config', 'BIG-IP iControl REST', 'OK',
                  f'{len(vs_items)} virtual servers, {len(pool_items)} pools, {len(self_items)} self IPs read')]
    pools = {p.get('fullPath') or f"/{p.get('partition', 'Common')}/{p.get('name')}": p for p in pool_items}
    vs_by_ep = {}
    for vs in vs_items:
        ip, port = _vs_endpoint(vs.get('destination'))
        if ip:
            vs_by_ep.setdefault((ip, port), []).append(vs)

    for vip_key, port, label, role in SERVICES:
        vip = i[vip_key]
        title = f'{label} virtual server {vip}:{port}'
        found = vs_by_ep.get((vip, port))
        if not found:
            results.append(_r('f5-config', title, 'FAIL', 'no virtual server with this destination (address and port)'))
            continue
        vs = found[0]
        if vs.get('disabled') or vs.get('enabled') is False:
            results.append(_r('f5-config', title, 'FAIL', f"virtual server {vs.get('name')} is disabled"))
            continue
        pool_name = vs.get('pool')
        if not pool_name:
            results.append(_r('f5-config', title, 'FAIL', f"virtual server {vs.get('name')} has no default pool (traffic steered by iRule/policy is not checked)"))
            continue
        pool = pools.get(pool_name)
        if not pool:
            results.append(_r('f5-config', title, 'FAIL', f'pool {pool_name} not found'))
            continue
        members = (pool.get('membersReference') or {}).get('items') or []
        member_ips, bad_ports = set(), []
        for m in members:
            addr = _strip_rd(m.get('address') or m.get('name', '').rsplit(':', 1)[0])
            member_ips.add(addr)
            mport = m.get('name', '').rsplit(':', 1)[-1]
            if mport.isdigit() and int(mport) != port:
                bad_ports.append(f'{addr}:{mport}')
        expected = masters if role == 'masters' else (workers or masters)
        missing, extra = expected - member_ips, member_ips - expected
        who = 'control-plane nodes' if role == 'masters' else ('worker nodes' if workers else 'control-plane nodes (no workers defined)')
        if missing:
            results.append(_r('f5-config', title, 'FAIL', f"pool {pool_name} is missing {who}: {', '.join(sorted(missing))}"))
            continue
        notes = []
        if extra:
            notes.append(f"extra members not in inventory: {', '.join(sorted(extra))}")
        if bad_ports:
            notes.append(f"member ports differ from {port}: {', '.join(bad_ports)}")
        if not pool.get('monitor'):
            notes.append('pool has no pool-level health monitor (check member-level monitors manually)')
        detail = f"pool {pool_name} contains all expected {who}"
        results.append(_r('f5-config', title, 'WARN' if notes else 'OK', detail + ('; ' + '; '.join(notes) if notes else '')))

    self_ips = {_strip_rd(s.get('address', '')) for s in self_items}
    for ip in i['f5_self_ips']:
        if ip in self_ips:
            results.append(_r('f5-config', f'F5 self IP {ip}', 'OK', 'present on the BIG-IP'))
        else:
            results.append(_r('f5-config', f'F5 self IP {ip}', 'WARN',
                              'not found as a self IP on this BIG-IP (SNAT pool or floating/other-device addresses are not self IPs; verify inventory)'))
    return results


def f5_tcp_checks(v):
    f = f5_cfg(v)
    if not f['enabled'] or f['tcp_probe'] == 'off':
        return []
    i = v['infrastructure']
    timeout = int(f['timeout_seconds'])
    bad = 'FAIL' if f['tcp_probe'] == 'require' else 'WARN'

    def probe(svc):
        vip_key, port, label, _ = svc
        vip = i[vip_key]
        title = f'{label} TCP {vip}:{port}'
        try:
            socket.create_connection((vip, port), timeout=timeout).close()
            return _r('f5-tcp', title, 'OK', 'connection accepted')
        except ConnectionRefusedError:
            return _r('f5-tcp', title, bad, 'connection refused: the address answered but nothing accepted the connection '
                                            '(normal before the cluster runs; otherwise the virtual server is missing/offline)')
        except socket.timeout:
            return _r('f5-tcp', title, bad, 'timed out: no answer (routing, firewall/NSG or virtual server not listening)')
        except OSError as e:
            return _r('f5-tcp', title, bad, f'{e.strerror or e}')

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(probe, SERVICES))


# ----------------------------------------------------------------------------- entry points
def run(v, environ=None):
    environ = os.environ if environ is None else environ
    validate_config(v)
    d, f = dns_cfg(v), f5_cfg(v)
    results = dns_checks(v, environ) + f5_rest_checks(v, environ) + f5_tcp_checks(v)
    active = d['enabled'] or (f['enabled'] and (f['rest']['enabled'] or f['tcp_probe'] != 'off'))
    return {'enabled': bool(active), 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'results': results}


def print_report(report):
    """Print the report; return True when nothing failed."""
    if not report['enabled'] or not report['results']:
        print('NETCHECK: no DNS/F5 checks enabled in inventory/infrastructure.yml')
        return True
    for r in report['results']:
        print('  %-4s %-8s %s%s' % (r['status'], r['category'], r['name'], (' -> ' + r['detail']) if r['detail'] else ''))
    counts = {s: sum(1 for r in report['results'] if r['status'] == s) for s in ('OK', 'WARN', 'FAIL')}
    print('NETCHECK: %d OK, %d WARN, %d FAIL' % (counts['OK'], counts['WARN'], counts['FAIL']))
    return counts['FAIL'] == 0
