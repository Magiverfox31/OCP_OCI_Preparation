#!/usr/bin/env python3
"""Inventory-driven OpenShift agent artifacts. No OCI VM provisioning is performed."""
import argparse, concurrent.futures, datetime, hashlib, ipaddress, json, os, re, shutil, subprocess, sys
from pathlib import Path
import importlib.util, tarfile, difflib
OCI_IMAGE_NAME='master_node_image.oci'
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
os.umask(0o077)
ROOT=Path(__file__).resolve().parents[1]
SECRET_DIR=ROOT/'secret'
PULL_SECRET_NAME='pull-secret.json';SSH_KEY_NAME='ssh-key.pub'
def secret_paths(name):return SECRET_DIR/str(name)/PULL_SECRET_NAME,SECRET_DIR/str(name)/SSH_KEY_NAME
FILES=['cluster.yml','nodes.yml','network.yml','infrastructure.yml']
TEST_FILES=['urls.yml','dns_f5.yml']
def die(s): raise RuntimeError(s)
def load_script(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def load_netcheck():return load_script('netcheck')
def env_true(name):return os.environ.get(name,'').strip().lower() in ('1','true','yes')
def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def read_inventory(collect=None):
 """Load the four build inventory files. With collect=[] problems are appended (and the file skipped) instead of raised."""
 inv={}
 for filename in FILES:
  f=ROOT/'inventory'/filename
  try:
   if not f.is_file():die(f'Missing inventory: {f}')
   try:value=yaml.safe_load(f.read_text())
   except yaml.YAMLError as e:
    m=getattr(e,'problem_mark',None);where=f' (line {m.line+1}, column {m.column+1})' if m else ''
    die(f'inventory/{filename}: YAML syntax error{where}: {getattr(e,"problem",None) or e}. Check quotes, colons and brackets on that line; paste file paths, not file contents.')
   if not isinstance(value,dict):die(f'inventory/{filename}: expected a mapping at the top level')
   inv.update(value)
  except RuntimeError as e:
   if collect is None:raise
   collect.append(str(e))
 legacy=sorted({'dns_checks','f5_checks'}&set(inv.get('infrastructure') or {})) if isinstance(inv.get('infrastructure'),dict) else []
 if legacy:
  msg='inventory/infrastructure.yml: %s moved to testing/dns_f5.yml (the testing phase); remove them from infrastructure.yml'%' and '.join(legacy)
  if collect is None:die(msg)
  collect.append(msg)
 try:normalize_nodes(inv)
 except Exception as e:
  if collect is None:raise
  collect.append(f'nodes.yml: {e}');inv.setdefault('nodes',[])
 return inv
def read_testing(v,collect=None):
 """Merge the testing-phase files (testing/urls.yml, testing/dns_f5.yml) into the inventory dict. Used only by preflight and netcheck."""
 for filename in TEST_FILES:
  f=ROOT/'testing'/filename
  try:
   if not f.is_file():die(f'Missing testing/{filename}')
   try:value=yaml.safe_load(f.read_text())
   except yaml.YAMLError as e:
    m=getattr(e,'problem_mark',None);where=f' (line {m.line+1}, column {m.column+1})' if m else ''
    die(f'testing/{filename}: YAML syntax error{where}: {getattr(e,"problem",None) or e}')
   if not isinstance(value,dict):die(f'testing/{filename}: expected a mapping at the top level')
   if filename=='urls.yml':v['preflight']=value.get('preflight') or {}
   else:
    infra=v.setdefault('infrastructure',{})
    for k in ('dns_checks','f5_checks'):
     if k in value:infra[k]=value[k]
  except RuntimeError as e:
   if collect is None:raise
   collect.append(str(e))
HOST_KEYS={'name','ip','mac','role','interface','prefix_length','mtu','gateway','dns_servers','root_device_hint','oci_vm_id'}
DEFAULT_KEYS={'interface','prefix_length','mtu','root_device_hint'}
def normalize_nodes(inv):
 """Build the flat inv['nodes'] list the rest of the code uses.

 nodes.yml may list hosts under masters:/workers: (role implied) or in the older nodes: list (role per host).
 Shared values come from node_defaults; the subnet prefix defaults to the machine_network prefix.
 A value given on a host overrides the default."""
 grouped='masters' in inv or 'workers' in inv
 if grouped and 'nodes' in inv:die('nodes.yml: use either masters:/workers: or the older nodes: list, not both')
 hosts=[]
 if grouped:
  for role,key in (('master','masters'),('worker','workers')):
   lst=inv.get(key) or []
   if not isinstance(lst,list):die(f'nodes.yml: {key} must be a list')
   for h in lst:
    if not isinstance(h,dict):die(f'nodes.yml: every entry in {key} must be a mapping with name, ip and mac')
    if h.get('role',role)!=role:die(f"nodes.yml: host {h.get('name')} is listed under {key} but has role {h.get('role')}")
    hosts.append(dict(h,role=role))
 else:
  lst=inv.get('nodes') or []
  if not isinstance(lst,list) or not all(isinstance(h,dict) for h in lst):die('nodes.yml: nodes must be a list of mappings')
  hosts=[dict(h) for h in lst]
 d=inv.get('node_defaults') or {}
 if not isinstance(d,dict):die('nodes.yml: node_defaults must be a mapping')
 bad=set(d)-DEFAULT_KEYS
 if bad:die('nodes.yml: unknown node_defaults key(s) %s; allowed: %s'%(', '.join(sorted(bad)),', '.join(sorted(DEFAULT_KEYS))))
 prefix=None
 try:prefix=ipaddress.ip_network(str((inv.get('network') or {}).get('machine_network','')),strict=False).prefixlen
 except ValueError:pass
 for h in hosts:
  label=h.get('name') or h.get('ip') or '<unnamed host>'
  unknown=set(h)-HOST_KEYS
  if unknown:die('nodes.yml: host %s has unknown key(s) %s; allowed: %s'%(label,', '.join(sorted(unknown)),', '.join(sorted(HOST_KEYS))))
  for k in ('name','ip','mac'):
   if not h.get(k):die(f'nodes.yml: host {label} is missing "{k}"')
  for k in DEFAULT_KEYS:
   if h.get(k) in (None,''):h.pop(k,None)
   if k not in h and d.get(k) not in (None,''):h[k]=d[k]
  if 'prefix_length' not in h and prefix is not None:h['prefix_length']=prefix
  for k in ('gateway','dns_servers'):
   if not h.get(k):h.pop(k,None)
  if not h.get('interface'):die(f'nodes.yml: host {label} has no interface and node_defaults.interface is not set')
  if 'prefix_length' not in h:die(f'nodes.yml: host {label} has no prefix_length and network.machine_network is not a valid CIDR to derive it from')
  h.setdefault('root_device_hint','')
  h.setdefault('mtu',9000)
 inv['nodes']=hosts
 net=inv.get('network')
 if isinstance(net,dict) and not net.get('ntp_servers'):net['ntp_servers']=[]
 cl=inv.get('cluster')
 if isinstance(cl,dict):
  cl.setdefault('minimal_iso',True)
  if not cl.get('mirror'):cl['mirror']={'enabled':False}
  if not cl.get('image_build'):cl['image_build']={'proxy':'inherit'}
def ipaddr(value,label):
 try:return ipaddress.ip_address(value)
 except (ValueError,TypeError):die(f'{label} must be an IP address, got {value!r}')
def validate_testing(v,collect=None):
 """Validate testing/ settings (URL list, DNS/F5 checks). Same collect convention as validate()."""
 def S(fn):
  try:fn()
  except KeyError as e:
   if collect is None:raise
   collect.append(f'missing inventory key {e} needed by the checks')
  except Exception as e:
   if collect is None:raise
   collect.append(str(e) or repr(e))
 pf=v.get('preflight') or {}
 def q():
  if pf.get('enabled',True):
   mir=bool(((v.get('cluster') or {}).get('mirror') or {}).get('enabled'))
   if not isinstance(pf.get('urls'),list) or (not pf['urls'] and not mir):die('testing/urls.yml: urls must be a non-empty list (or set enabled: false)')
   if not all(isinstance(u,str) and u.strip() for u in (pf['urls']+list(pf.get('urls_when_mirror') or []))):die('testing/urls.yml: urls and urls_when_mirror entries must be non-empty strings')
   if int(pf.get('timeout_seconds',10))<1:die('testing/urls.yml: timeout_seconds must be >= 1')
   if pf.get('http_client','auto') not in ('auto','curl','urllib'):die(f"testing/urls.yml: http_client must be auto, curl or urllib, got {pf.get('http_client')!r}")
   if pf.get('ca_bundle') and not Path(pf['ca_bundle']).is_file():die(f"testing/urls.yml: missing ca_bundle {pf['ca_bundle']}")
 S(q)
 def f5():
  i=v['infrastructure']
  if (i.get('f5_checks') or {}).get('enabled',True) and (not isinstance(i.get('f5_self_ips'),list) or not i['f5_self_ips']):die('infrastructure.yml: f5_self_ips must be a non-empty list of the BIG-IP self IP addresses while testing/dns_f5.yml has f5_checks.enabled: true')
 S(f5)
 S(lambda:load_netcheck().validate_config(v))
MIRROR_KEYS={'enabled','registry','sources','ca_bundle_file','sources_key'}
def validate_mirror(v):
 c=v['cluster'];mi=c.get('mirror') or {};ib=c.get('image_build') or {}
 if not isinstance(mi,dict):die('cluster.yml: mirror must be a mapping')
 bad=set(mi)-MIRROR_KEYS
 if bad:die('cluster.yml: unknown mirror key(s) %s; allowed: %s'%(', '.join(sorted(bad)),', '.join(sorted(MIRROR_KEYS))))
 if not isinstance(mi.get('enabled',False),bool):die(f"cluster.yml: mirror.enabled must be true or false (without quotes), got {mi.get('enabled')!r}")
 if mi.get('enabled'):
  reg=str(mi.get('registry') or '')
  if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',reg) or '://' in reg:die(f"cluster.yml: mirror.registry must look like registry.example.internal:8443/ocp4/openshift4 (host[:port]/path, no https://), got {reg!r}")
  src=mi.get('sources')
  if not isinstance(src,list) or not src or not all(isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',x) for x in src):die(f"cluster.yml: mirror.sources must be a non-empty list of repositories such as quay.io/openshift-release-dev/ocp-release, got {src!r}")
  if mi.get('sources_key','imageContentSources') not in ('imageContentSources','imageDigestSources'):die(f"cluster.yml: mirror.sources_key must be imageContentSources or imageDigestSources, got {mi.get('sources_key')!r}")
  if mi.get('ca_bundle_file'):
   p=Path(str(mi['ca_bundle_file']))
   if not p.is_file():die(f'cluster.yml: missing mirror.ca_bundle_file: {p}')
   if '-----BEGIN CERTIFICATE-----' not in p.read_text():die('cluster.yml: mirror.ca_bundle_file must contain a PEM certificate')
 if not isinstance(ib,dict) or set(ib)-{'proxy'}:die('cluster.yml: image_build may contain only the key proxy')
 if ib.get('proxy','inherit') not in ('inherit','cluster','none'):die(f"cluster.yml: image_build.proxy must be inherit, cluster or none, got {ib.get('proxy')!r}")
 if ib.get('proxy')=='cluster' and not (v.get('proxy') or {}).get('enabled',False):die('cluster.yml: image_build.proxy is "cluster" but network.yml proxy.enabled is false')
def validate(v,collect=None):
 """Validate the inventory. Normal mode raises on the first problem. With collect=[] every group of checks runs and each problem is appended as a message naming the field and value."""
 st={}
 def S(label,fn):
  try:fn()
  except KeyError as e:
   if collect is None:raise
   collect.append(f'{label}: missing inventory key {e}')
  except Exception as e:
   if collect is None:raise
   collect.append(str(e) or repr(e))
 try:c=v['cluster'];n=v['network'];i=v['infrastructure'];hosts=v['nodes']
 except KeyError as e:
  if collect is None:raise
  collect.append(f'missing inventory section {e}');return None
 def a():
  if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',str(c['name'])):die(f"cluster.yml: invalid cluster.name {c['name']!r} (lowercase letters, digits and hyphens)")
  if not re.fullmatch(r'[a-zA-Z0-9.-]+',str(c['base_domain'])) or '.' not in str(c['base_domain']):die(f"cluster.yml: invalid base_domain {c['base_domain']!r}")
  if not str(c['ocp_version']).startswith('4.22'):die(f"cluster.yml: ocp_version {c['ocp_version']!r}; this release is validated for OCP 4.22 only")
  if c['architecture']!='x86_64':die(f"cluster.yml: architecture {c['architecture']!r}; only x86_64 is supported")
  if not isinstance(c['minimal_iso'],bool):die(f"cluster.yml: minimal_iso must be true or false (without quotes), got {c['minimal_iso']!r}")
  if n['network_type']!='OVNKubernetes':die(f"network.yml: network_type {n['network_type']!r}; OCP 4.22 requires OVNKubernetes")
  if i['platform']!='oci' or i['dns_provider']!='infoblox' or i['loadbalancer_provider']!='f5':die(f"infrastructure.yml: supported profile is platform: oci, dns_provider: infoblox, loadbalancer_provider: f5 (lowercase); got {i['platform']!r}, {i['dns_provider']!r}, {i['loadbalancer_provider']!r}")
 S('profile',a)
 def b():
  nets={k:ipaddress.ip_network(str(n[k]),strict=False) for k in ('machine_network','cluster_network','service_network')}
  st['nets']=nets;ks=list(nets)
  for x in range(len(ks)):
   for y in range(x+1,len(ks)):
    if nets[ks[x]].version==nets[ks[y]].version and nets[ks[x]].overlaps(nets[ks[y]]):die(f'network.yml: {ks[x]} {nets[ks[x]]} overlaps {ks[y]} {nets[ks[y]]}; the three networks must not overlap')
  if not nets['cluster_network'].prefixlen<int(n['host_prefix'])<=32:die(f"network.yml: host_prefix {n['host_prefix']} must be larger than the cluster_network prefix (/{nets['cluster_network'].prefixlen}) and at most 32")
 S('networks',b)
 px=v.get('proxy') or {}
 def p():
  if px.get('enabled',False):
   if not (px.get('http_proxy') or px.get('https_proxy')):die('network.yml: proxy.enabled requires http_proxy and/or https_proxy')
   for k in ('http_proxy','https_proxy'):
    if px.get(k) and not re.fullmatch(r'http://\S+',str(px[k])):die(f'network.yml: proxy.{k} must be an http:// URL (OpenShift supports only http:// proxy URLs), got {px[k]!r}')
   if px.get('additional_trust_bundle_file'):
    tb=Path(px['additional_trust_bundle_file'])
    if not tb.is_file():die(f'network.yml: missing proxy.additional_trust_bundle_file: {tb}')
    if '-----BEGIN CERTIFICATE-----' not in tb.read_text():die('network.yml: proxy.additional_trust_bundle_file must contain a PEM certificate')
   if px.get('additional_trust_bundle_policy','Proxyonly') not in ('Proxyonly','Always'):die('network.yml: proxy.additional_trust_bundle_policy must be Proxyonly or Always')
 S('proxy',p)
 S('mirror',lambda:validate_mirror(v))
 def d1():ipaddr(c['rendezvous_ip'],'cluster.yml: rendezvous_ip')
 S('rendezvous_ip',d1)
 def d2():
  ntp=n.get('ntp_servers') or []
  if not isinstance(ntp,list):die(f'network.yml: ntp_servers must be a list such as [10.0.0.1, 10.0.0.2], got {ntp!r}')
  for x in ntp:
   if not (isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9:._-]+',x)):die(f'network.yml: ntp_servers entry {x!r} must be a host name or IP address without spaces, ports or URL prefix')
 S('ntp',d2)
 def d3():
  for k in ('api_vip','ingress_vip'):ipaddr(i[k],f'infrastructure.yml: {k} (the F5 virtual server IP, not a host name)')
 S('vips',d3)
 def d4():
  if not isinstance(n['dns_servers'],list) or not n['dns_servers']:die('network.yml: dns_servers must be a non-empty list of the Infoblox resolver IPs')
  for ip in (i.get('f5_self_ips') or []):ipaddr(ip,'infrastructure.yml: f5_self_ips entry')
  for ip in n['dns_servers']:ipaddr(ip,'network.yml: dns_servers entry')
 S('f5_dns',d4)
 def h():
  if not isinstance(hosts,list) or len(hosts)<3:die('nodes.yml: define at least 3 nodes')
  if sum(x['role']=='master' for x in hosts)!=3:die('nodes.yml: exactly 3 masters are required in this supported profile')
 S('hosts',h)
 names=set();ips=set();macs=set()
 for x in (hosts if isinstance(hosts,list) else []):
  def hx(x=x):
   w=f"nodes.yml host {x.get('name')!r}"
   if x['role'] not in ('master','worker'):die(f"{w}: role must be master or worker")
   if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*',x['name']):die(f"{w}: invalid host name")
   ipaddr(x['ip'],f'{w}: ip');ipaddr(x.get('gateway') or n['gateway'],f'{w}: gateway')
   if 'nets' in st and ipaddress.ip_address(x['ip']) not in st['nets']['machine_network']:die(f"{w}: IP {x['ip']} is not inside network.machine_network {st['nets']['machine_network']}")
   if 'mtu' in x and not (isinstance(x['mtu'],int) and not isinstance(x['mtu'],bool) and 576<=x['mtu']<=9216):die(f"{w}: mtu must be a whole number between 576 and 9216 (no quotes), got {x['mtu']!r}")
   if x['root_device_hint'] and not str(x['root_device_hint']).startswith('/dev/'):die(f"{w}: root_device_hint must be a device path such as /dev/sda, got {x['root_device_hint']!r}")
   if not 1<=int(x['prefix_length'])<=32:die(f"{w}: invalid prefix_length {x['prefix_length']!r}")
   if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',str(x['mac'])):die(f"{w}: invalid MAC {x['mac']!r}; use the form 02:00:17:04:ed:b5 and nothing else (no interface name)")
   dup=[k for k,seen,val in (('name',names,x['name']),('IP',ips,x['ip']),('MAC',macs,str(x['mac']).lower())) if val in seen]
   names.add(x['name']);ips.add(x['ip']);macs.add(str(x['mac']).lower())
   if dup:die(f"{w}: duplicate {'/'.join(dup)}; {x['name']} ({x['ip']}, {x['mac']}) repeats a value used by an earlier host")
   for dns in x.get('dns_servers') or n['dns_servers']:ipaddr(dns,f'{w}: dns_servers entry')
  S('host',hx)
 def r():
  if c['rendezvous_ip'] not in {x['ip'] for x in hosts if x['role']=='master'}:die(f"cluster.yml: rendezvous_ip {c['rendezvous_ip']} must match the IP of one master in nodes.yml")
 S('rendezvous',r)
 def f():
  old=[k for k in ('pull_secret_file','ssh_public_key_file') if k in c]
  if old:die(f"cluster.yml: {' and '.join(old)} {'is' if len(old)==1 else 'are'} no longer used (v1.13.0); delete the line(s) and put the files in secret/{c.get('name') or '<cluster-name>'}/ as {PULL_SECRET_NAME} and {SSH_KEY_NAME}")
  ps,sk=secret_paths(c['name'])
  d=ps.parent
  if not d.is_dir():die(f"secrets: folder secret/{c['name']}/ does not exist; create it and put {PULL_SECRET_NAME} and {SSH_KEY_NAME} inside (the folder name must equal cluster.name)")
  for p in (ps,sk):
   if not p.is_file():die(f"secrets: missing file secret/{c['name']}/{p.name}")
  try:js=json.loads(ps.read_text())
  except ValueError as e:die(f"secrets: secret/{c['name']}/{PULL_SECRET_NAME} is not valid JSON ({e}); download the pull secret from console.redhat.com and save it unchanged")
  if not isinstance(js,dict) or not isinstance(js.get('auths'),dict) or not js['auths']:die(f"secrets: secret/{c['name']}/{PULL_SECRET_NAME} has no \"auths\" section; it does not look like a pull secret")
  k=sk.read_text().strip()
  if 'PRIVATE KEY' in k:die(f"secrets: secret/{c['name']}/{SSH_KEY_NAME} contains a PRIVATE key; put the public key (.pub) there and keep the private key elsewhere")
  if not k.startswith(('ssh-rsa ','ssh-ed25519 ','ecdsa-sha2-')):die(f"secrets: secret/{c['name']}/{SSH_KEY_NAME} does not contain an SSH public key (it should start with ssh-ed25519, ssh-rsa or ecdsa-sha2-)")
 S('secrets',f)
 def z():
  if c.get('release_image') and not re.fullmatch(r'\S+',str(c['release_image'])):die('cluster.yml: release_image must not contain whitespace')
 S('release_image',z)
 if collect is not None:return None
 ps,sk=secret_paths(c['name'])
 return ps.read_text().strip(),sk.read_text().strip()
def meta(run):return json.loads((run/'run.json').read_text())
def current_run():
 f=ROOT/'work'/'active-run.json'
 if not f.exists():die('No active prepared run; run prepare first')
 return Path(json.loads(f.read_text())['path'])
def write_json(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def mirror_data(v):
 """Mirror registry settings for install-config, or None when mirror.enabled is false."""
 mi=(v['cluster'].get('mirror') or {})
 if not mi.get('enabled',False):return None
 return {'key':mi.get('sources_key','imageContentSources'),'registry':mi['registry'],'sources':mi['sources'],'host':str(mi['registry']).split('/')[0].rsplit(':',1)[0] if not str(mi['registry']).startswith('[') else str(mi['registry']).split('/')[0]}
def proxy_data(v):
 """Return the proxy block for install-config, or None when disabled. noProxy always includes the cluster's own networks (and the mirror registry host when a mirror is used)."""
 px=v.get('proxy') or {}
 if not px.get('enabled',False):return None
 n=v['network'];c=v['cluster']
 extra=px.get('no_proxy') or []
 if isinstance(extra,str):extra=extra.split(',')
 mi=mirror_data(v)
 items=['localhost','127.0.0.1','.svc','.cluster.local',f"api-int.{c['name']}.{c['base_domain']}",str(n['machine_network']),str(n['cluster_network']),str(n['service_network'])]+([mi['host']] if mi else [])+[x.strip() for x in extra if x and x.strip()]
 no_proxy=','.join(dict.fromkeys(items))
 return {'http_proxy':px.get('http_proxy') or '','https_proxy':px.get('https_proxy') or '','no_proxy':no_proxy}
def trust_data(v):
 """additionalTrustBundle for install-config: proxy CA and/or mirror registry CA. Policy is Always when a mirror CA is present."""
 px=v.get('proxy') or {};mi=(v['cluster'].get('mirror') or {});parts=[];policy=px.get('additional_trust_bundle_policy','Proxyonly')
 if px.get('enabled',False) and px.get('additional_trust_bundle_file'):parts.append(Path(px['additional_trust_bundle_file']).read_text().strip())
 if mi.get('enabled',False) and mi.get('ca_bundle_file'):parts.append(Path(mi['ca_bundle_file']).read_text().strip());policy='Always'
 return {'bundle':'\n'.join(parts),'policy':policy} if parts else None
def probe_url(client,url,pf):
 """Probe one URL with curl or the built-in HTTP client. Any HTTP answer (even 3xx/4xx/5xx) means reachable; redirects are not followed."""
 target=url if '://' in url else 'https://'+url
 kind,curl=client
 t=int(pf.get('timeout_seconds',10))
 if kind=='urllib':
  nt=load_script('nettools')
  try:
   status,_=nt.urllib_fetch(target,method='HEAD',timeout=t,proxy=pf.get('proxy') or '',ca_bundle=pf.get('ca_bundle') or '',direct=bool(pf.get('direct')))
  except nt.FetchError as e:
   return {'url':target,'ok':False,'http_code':'','curl_rc':None,'detail':str(e)}
  return {'url':target,'ok':True,'http_code':str(status),'curl_rc':None,'detail':''}
 cmd=[curl,'-sS','-I','-o','/dev/null','-w','%{http_code}','--connect-timeout',str(t),'--max-time',str(t)]
 if pf.get('proxy'):cmd+=['-x',pf['proxy']]
 elif pf.get('direct'):cmd+=['--noproxy','*']
 if pf.get('ca_bundle'):cmd+=['--cacert',pf['ca_bundle']]
 r=subprocess.run(cmd+[target],capture_output=True,text=True)
 code=r.stdout.strip()
 ok=r.returncode==0 and code not in ('','000')
 return {'url':target,'ok':ok,'http_code':code,'curl_rc':r.returncode,'detail':'' if ok else (r.stderr.strip() or 'no HTTP response')}
def http_client(setting):
 """('curl', path) or ('urllib', None) according to preflight.http_client and what is installed."""
 curl=shutil.which('curl')
 if setting=='curl':
  if not curl:die('preflight.http_client is "curl" but curl is not installed; use "auto" or "urllib"')
  return ('curl',curl)
 if setting=='urllib' or not curl:return ('urllib',None)
 return ('curl',curl)
def preflight_check(v):
 """Probe the OCP allowlist URLs. Returns report dict; any HTTP response counts as reachable."""
 pf=v.get('preflight') or {}
 if not pf.get('enabled',True):return {'enabled':False,'results':[]}
 client=http_client(pf.get('http_client','auto'))
 label='curl' if client[0]=='curl' else 'built-in Python HTTP client'+('' if pf.get('http_client')=='urllib' else ' (curl not found)')
 mi=mirror_data(v)
 jobs=[(u,pf) for u in (pf.get('urls_when_mirror') or [] if mi else pf['urls'])]
 if mi:  # disconnected: test the mirror registry itself, directly unless mirror_probe_via_proxy is true
  pf2=dict(pf);pf2['ca_bundle']=(v['cluster'].get('mirror') or {}).get('ca_bundle_file') or pf.get('ca_bundle','')
  if not pf.get('mirror_probe_via_proxy',False):pf2['proxy']='';pf2['direct']=True
  jobs.append(('https://'+str(mi['registry']).split('/')[0]+'/v2/',pf2))
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
  results=list(ex.map(lambda j:probe_url(client,j[0],j[1]),jobs))
 return {'enabled':True,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'proxy':pf.get('proxy') or '','client':label,'results':results}
def print_report(rep):
 if not rep['enabled']:print('PREFLIGHT: disabled in testing/urls.yml');return True
 bad=[r for r in rep['results'] if not r['ok']]
 for r in rep['results']:print('  %-4s %-45s %s'%('OK' if r['ok'] else 'FAIL',r['url'],('HTTP '+r['http_code']) if r['ok'] else r['detail']))
 print('PREFLIGHT: %d/%d URLs reachable (client: %s)'%(len(rep['results'])-len(bad),len(rep['results']),rep.get('client','n/a')))
 return not bad
def tool_checks(v):
 """Required and optional tools on the bastion. Returns result dicts."""
 out=[]
 want=(v.get('cluster') or {}).get('ocp_version','')
 for t,why in (('openshift-install','builds the agent ISO'),('qemu-img','converts the ISO to qcow2'),('nmstatectl','used by the installer for static networking'),('tar','builds master_node_image.oci (the factory itself uses Python tarfile; tar is for manual checks)')):
  p=shutil.which(t)
  if not p:out.append(('Tools',t,'FAIL' if t!='tar' else 'WARN',f'not installed ({why}); run playbooks/dependencies.yml or install it'));continue
  det=p
  if t=='openshift-install':
   try:
    ver=subprocess.run([p,'version'],capture_output=True,text=True,timeout=30).stdout
    if want and str(want) not in ver:out.append(('Tools',t,'FAIL',f'version mismatch: inventory expects {want}, installed reports {ver.splitlines()[0] if ver else "nothing"}'));continue
    det+=' '+(ver.splitlines()[0] if ver else '')
   except Exception as e:out.append(('Tools',t,'FAIL',f'could not run: {e}'));continue
  out.append(('Tools',t,'PASS',det))
 for t,why in (('curl','URL/F5 checks fall back to the built-in Python client'),('dig','DNS checks fall back to the built-in Python resolver'),('nc','manual port tests only; /dev/tcp or python3 can replace it')):
  p=shutil.which(t) or (shutil.which('ncat') if t=='nc' else None)
  out.append(('Tools',t,'PASS' if p else 'WARN',p or f'optional, not installed ({why})'))
 return out
def secret_checks(v):
 """Permission and content hints for secret/<cluster>/ (never prints secret text)."""
 out=[];c=v.get('cluster') or {}
 if not c.get('name'):return out
 ps,sk=secret_paths(c['name'])
 for p in (ps,sk):
  if p.is_file():
   m=p.stat().st_mode&0o077
   out.append(('Secrets',f'secret/{c["name"]}/{p.name}','WARN' if m else 'PASS',f'group/other can access it (mode {oct(p.stat().st_mode&0o777)}); run chmod 600' if m else 'present, owner-only'))
 if ps.parent.is_dir() and ps.parent.stat().st_mode&0o077:out.append(('Secrets',f'secret/{c["name"]}/','WARN',f'folder is accessible to group/other (mode {oct(ps.parent.stat().st_mode&0o777)}); run chmod 700'))
 mi=(c.get('mirror') or {})
 if mi.get('enabled') and mi.get('registry') and ps.is_file():
  try:
   host=str(mi['registry']).split('/')[0];auths=json.loads(ps.read_text()).get('auths',{})
   out.append(('Secrets','mirror credentials','PASS' if any(str(k).split('/')[0]==host for k in auths) else 'WARN',f'pull secret has an entry for {host}' if any(str(k).split('/')[0]==host for k in auths) else f'pull secret has no entry for the mirror registry {host}; add its credentials (ignore if the registry is anonymous)'))
  except Exception:pass
 return out
COLOR=False
def paint(line,state):
 """ANSI colours for the terminal copy of the preflight report: PASS green, FAIL red, WARN yellow."""
 G,R,Y,E='\033[32m','\033[31m','\033[33m','\033[0m'
 for word,col in (('PASS',G),('FAIL',R),('WARN',Y)):
  if line.startswith('  '+word+' '):return '  '+col+word+E+line[2+len(word):]
 if line.startswith('FAILED:'):state[0]='f';return R+line+E
 if line.startswith('WARNINGS:'):state[0]='w';return Y+line+E
 if line.startswith('RESULT: ALL'):return G+line+E
 if line.startswith('RESULT:'):return R+line+E
 if line.startswith('PASSED:'):
  m=re.match(r'PASSED: (\d+)(\s+)WARNINGS: (\d+)(\s+)FAILED: (\d+)',line)
  if m:return '%sPASSED: %s%s%s%sWARNINGS: %s%s%s%sFAILED: %s%s'%(G,m.group(1),E,m.group(2),Y,m.group(3),E,m.group(4),R if m.group(5)!='0' else G,m.group(5),E)
 if line.startswith('  - ['):return (R if state[0]=='f' else Y)+line+E
 return line
def preflight():
 """Run EVERY check and report all results; never stops at the first problem."""
 import time
 res=[];ts=datetime.datetime.now(datetime.timezone.utc)
 errs=[];v=read_inventory(errs)
 unreadable=any(k not in v for k in ('cluster','network','infrastructure','nodes'))
 if not unreadable:
  try:validate(v,errs)
  except Exception as e:errs.append(str(e))
 if errs:
  for e in errs:res.append(('Inventory','inventory value','FAIL',e))
 else:res.append(('Inventory','inventory files','PASS','all four build inventory files valid'))
 terrs=[];read_testing(v,terrs)
 if not terrs and not unreadable:validate_testing(v,terrs)
 if terrs:
  for e in terrs:res.append(('Test settings','testing/ value','FAIL',e))
 else:res.append(('Test settings','testing/ files','PASS','urls.yml and dns_f5.yml valid'))
 if (ROOT/'inventory'/'preflight.yml').exists():res.append(('Test settings','inventory/preflight.yml','WARN','no longer used; the URL list is now testing/urls.yml (delete the old file)'))
 why='an inventory file above is unreadable or incomplete' if unreadable else ('testing/ settings above are invalid' if terrs else None)
 res+=secret_checks(v)
 res+=tool_checks(v)
 try:
  rep=preflight_check(v)
  if not rep['enabled']:res.append(('URLs','preflight','WARN','disabled in testing/urls.yml'))
  for r in rep['results']:res.append(('URLs',r['url'],'PASS' if r['ok'] else 'FAIL',('HTTP '+r['http_code']) if r['ok'] else r['detail']))
  if rep['enabled']:res.append(('URLs','client','PASS',rep.get('client','')+(', proxy '+rep['proxy'] if rep.get('proxy') else ', no proxy')))
 except Exception as e:res.append(('URLs','URL checks','FAIL','not run: '+why if why else f'could not run: {e!r}'))
 try:
  nc=load_netcheck();nrep=nc.run(v)
  if not nrep['results']:res.append(('DNS/F5','checks','WARN','none enabled in infrastructure.yml'))
  for r in nrep['results']:res.append(('DNS' if r['category']=='dns' else 'F5',r['name'],{'OK':'PASS'}.get(r['status'],r['status']),r['detail']))
 except Exception as e:res.append(('DNS/F5','DNS and F5 checks','FAIL','not run: '+why if why else f'could not run: {e!r}'))
 res=[(a,b,c_,' '.join(str(d).split())[:300]) for a,b,c_,d in res]
 fails=[r for r in res if r[2]=='FAIL'];warns=[r for r in res if r[2]=='WARN'];ok=[r for r in res if r[2]=='PASS']
 L=['PREFLIGHT FULL REPORT  '+ts.strftime('%Y-%m-%d %H:%M:%S UTC'),'']
 for g in dict.fromkeys(r[0] for r in res):
  L.append('== '+g)
  for r in res:
   if r[0]==g:L.append('  %-5s %-48s %s'%(r[2],r[1][:48],r[3]))
 L+=['','================ SUMMARY ================','PASSED: %d   WARNINGS: %d   FAILED: %d'%(len(ok),len(warns),len(fails))]
 if fails:L+=['','FAILED:']+['  - [%s] %s: %s'%(r[0],r[1],r[3]) for r in fails]
 if warns:L+=['','WARNINGS:']+['  - [%s] %s: %s'%(r[0],r[1],r[3]) for r in warns]
 L+=['','RESULT: '+('ALL CHECKS PASSED' if not fails else 'NOT READY - fix the FAILED items above and run again')]
 (ROOT/'work').mkdir(exist_ok=True)
 log=ROOT/'work'/('preflight-'+ts.strftime('%Y%m%dT%H%M%SZ')+'.log');log.write_text('\n'.join(L)+'\n')
 write_json(ROOT/'work'/('preflight-'+ts.strftime('%Y%m%dT%H%M%SZ')+'.json'),[{'group':a,'check':b,'status':c_,'detail':d} for a,b,c_,d in res])
 st=['']
 print('\n'.join(paint(x,st) for x in L) if COLOR else '\n'.join(L));print('\nLog saved to',log)
 if fails:sys.exit(1)
def netcheck():
 v=read_inventory();validate(v);read_testing(v);validate_testing(v);nc=load_netcheck()
 if not nc.print_report(nc.run(v)):die('DNS/F5 checks failed: see FAIL lines above')
def prepare():
 v=read_inventory();secret,ssh=validate(v);c=v['cluster']; name=c['name']
 active=ROOT/'work'/'active-run.json'
 if active.exists():die('An active run already exists. Finish or explicitly run discard before preparing a new one')
 run_id=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+os.urandom(3).hex()
 run=ROOT/'work'/name/run_id;review=run/'review';installer=run/'installer'
 review.mkdir(parents=True);installer.mkdir()
 env=Environment(loader=FileSystemLoader(str(ROOT/'templates')),undefined=StrictUndefined,keep_trailing_newline=True,trim_blocks=True,lstrip_blocks=True)
 data=dict(v,proxy_cfg=proxy_data(v),trust_cfg=trust_data(v),mirror_cfg=mirror_data(v),pull_secret_json=secret,ssh_public_key=ssh,masters_count=3,workers_count=sum(x['role']=='worker' for x in v['nodes']))
 for src,out in [('install-config.yaml.j2','install-config.yaml'),('agent-config.yaml.j2','agent-config.yaml')]:
  rendered=env.get_template(src).render(**data)
  yaml.safe_load(rendered)
  (installer/out).write_text(rendered)
  (review/(name+'-'+out)).write_text(rendered)
 meta_text=(ROOT/'templates'/'image_metadata.json').read_text()
 json.loads(meta_text)
 (review/(name+'-image_metadata.json')).write_text(meta_text)
 shutil.copytree(review,run/'generated')  # untouched originals, so approve can show exactly what you edited
 if (v['cluster'].get('mirror') or {}).get('enabled') and not (v['cluster'].get('release_image') or '').strip():print('NOTE: mirror is enabled but cluster.release_image is empty; for a disconnected build set it to the mirrored release image (or make sure openshift-install can resolve the release through the mirror).')
 # Record inventory snapshot and validate it cannot be altered unnoticed
 (run/'inventory').mkdir()
 for f in FILES:shutil.copy2(ROOT/'inventory'/f,run/'inventory'/f)
 checks={f:digest(review/f) for f in sorted(x.name for x in review.iterdir())}
 write_json(run/'run.json',{'cluster':name,'run_id':run_id,'version':c['ocp_version'],'status':'awaiting_approval','checksums':checks,'inventory_checksums':{f:digest(run/'inventory'/f) for f in FILES}})
 write_json(active,{'path':str(run)})
 print('PREPARED:',run,'\nFiles to review and edit if needed:',review,'\nWhen they are final run: python3 scripts/factory.py approve --run-id',run_id,'\nNote: prepare runs no connectivity tests; use playbooks/preflight.yml for those. Edit only the files in review/ (not installer/).')
def check_edited(name,filename,text,cluster):
 """Light sanity checks on the review files, which the operator may have edited by hand."""
 if filename.endswith('image_metadata.json'):
  try:d=json.loads(text)
  except ValueError as e:die(f'{filename}: not valid JSON ({e})')
  if not isinstance(d,dict) or 'version' not in d or 'externalLaunchOptions' not in d:die(f'{filename}: must contain "version" and "externalLaunchOptions"')
  return
 try:d=yaml.safe_load(text)
 except yaml.YAMLError as e:
  m=getattr(e,'problem_mark',None);die(f'{filename}: YAML syntax error'+(f' (line {m.line+1}, column {m.column+1})' if m else '')+f': {getattr(e,"problem",None) or e}')
 if not isinstance(d,dict):die(f'{filename}: expected a YAML mapping')
 if (d.get('metadata') or {}).get('name')!=cluster:die(f"{filename}: metadata.name must stay {cluster!r} (it names the run and the archive), found {(d.get('metadata') or {}).get('name')!r}")
 if filename.endswith('install-config.yaml'):
  for k in ('apiVersion','baseDomain','networking','pullSecret'):
   if not d.get(k):die(f'{filename}: required key {k!r} is missing or empty')
 else:
  if d.get('kind')!='AgentConfig':die(f"{filename}: kind must be AgentConfig, found {d.get('kind')!r}")
  if not d.get('rendezvousIP'):die(f'{filename}: rendezvousIP is missing')
  ipaddr(str(d['rendezvousIP']),f'{filename}: rendezvousIP')
  if not isinstance(d.get('hosts'),list) or not d['hosts']:die(f'{filename}: hosts must be a non-empty list')
def approve(run_id):
 run=current_run();m=meta(run)
 if run_id!=m['run_id']:die('Run ID mismatch')
 if m['status']!='awaiting_approval':die('Run not awaiting approval')
 for f,h in m['inventory_checksums'].items():
  if digest(ROOT/'inventory'/f)!=h:die('Inventory changed since prepare; discard and prepare again')
 for f in FILES:
  if digest(run/'inventory'/f)!=m['inventory_checksums'][f]:die('Inventory snapshot modified')
 name=m['cluster'];review=run/'review';gen=run/'generated';installer=run/'installer'
 approved={};changed=[];diff=[]
 for f in sorted(m['checksums']):
  p=review/f
  if not p.is_file():die(f'Missing review file {f}; run prepare again or restore it from {gen}')
  text=p.read_text();check_edited(name,f,text,name)
  approved[f]=digest(p)
  if approved[f]!=m['checksums'][f]:
   changed.append(f)
   diff+=[l for l in difflib.unified_diff((gen/f).read_text().splitlines(),text.splitlines(),'generated/'+f,'review/'+f,lineterm='') if not any(k in l for k in ('pullSecret','sshKey'))]
 for f in approved:
  std=f[len(name)+1:]
  if std in ('install-config.yaml','agent-config.yaml'):shutil.copy2(review/f,installer/std)
 m.update(status='approved',approved_checksums=approved,edited_files=changed,approved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),approved_by=os.environ.get('USER','unknown'))
 write_json(run/'run.json',m)
 (run/'approval-diff.txt').write_text('\n'.join(diff)+('\n' if diff else '') if changed else 'No manual edits: approved exactly as generated.\n')
 if changed:
  print('EDITED FILES APPROVED:',', '.join(changed));print('\n'.join(diff[:120]));print('(pullSecret/sshKey lines are never shown; full diff saved to %s)'%(run/'approval-diff.txt'))
 else:print('No manual edits: approving the files exactly as generated.')
 print('APPROVED',run)
def run_cmd(cmd,cwd,env=None):
 print('RUN:', ' '.join(cmd),flush=True)
 subprocess.run(cmd,cwd=cwd,check=True,env=env)
def build():
 run=current_run();m=meta(run)
 if m['status'] not in ('approved','build_failed'):die('Run is not approved')
 name=m['cluster']; installer=run/'installer';review=run/'review'
 for f,h in m.get('approved_checksums',m['checksums']).items():
  if digest(review/f)!=h:die('Reviewed file changed after approval; discard and prepare again, or approve again before building')
  standard=f[len(name)+1:]
  if m['status']=='approved' and standard in ('install-config.yaml','agent-config.yaml') and digest(installer/standard)!=h:die('Installer file changed; approval invalid')
 for f,h in m['inventory_checksums'].items():
  if digest(ROOT/'inventory'/f)!=h or digest(run/'inventory'/f)!=h:die('Inventory changed; approval invalid')
 if m['status']=='build_failed':
  # openshift-install consumes install-config.yaml/agent-config.yaml, so restore them from the approved, hash-verified review copies
  shutil.rmtree(installer,ignore_errors=True);installer.mkdir()
  for f in m.get('approved_checksums',m['checksums']):
   if f.endswith(('install-config.yaml','agent-config.yaml')):shutil.copy2(review/f,installer/f[len(name)+1:])
 try:
  installer_bin=shutil.which('openshift-install');qemu=shutil.which('qemu-img')
  if not installer_bin or not qemu:die('openshift-install and qemu-img must be installed in PATH')
  version=subprocess.run([installer_bin,'version'],capture_output=True,text=True,check=True).stdout
  if m['version'] not in version:die(f'Installer version mismatch: expected {m["version"]}; got {version.strip()}')
  env=dict(os.environ)
  inv_now=read_inventory();rel=(inv_now['cluster'].get('release_image') or '').strip()
  pm=(inv_now['cluster'].get('image_build') or {}).get('proxy','inherit')
  if pm=='none':
   for k in [k for k in env if k.lower() in ('http_proxy','https_proxy','no_proxy','all_proxy')]:del env[k]
   print('Image build proxy: none (proxy variables removed for openshift-install)')
  elif pm=='cluster':
   pd=proxy_data(inv_now)
   for k,val in (('http_proxy',pd['http_proxy']),('https_proxy',pd['https_proxy']),('no_proxy',pd['no_proxy'])):
    env[k]=val;env[k.upper()]=val
   print('Image build proxy: cluster proxy from network.yml')
  else:print('Image build proxy: inherit (shell environment unchanged)')
  if rel:env['OPENSHIFT_INSTALL_RELEASE_IMAGE_OVERRIDE']=rel;print('Using pinned release image:',rel)
  run_cmd([installer_bin,'agent','create','image','--dir',str(installer)],ROOT,env)
  iso=installer/'agent.x86_64.iso'
  if not iso.is_file() or iso.stat().st_size==0:die('Installer did not create a nonempty agent.x86_64.iso')
  artifacts=run/'artifacts';artifacts.mkdir(exist_ok=True)
  iso_dst=artifacts/(name+'-agent.x86_64.iso');shutil.copy2(iso,iso_dst)
  qcow=artifacts/(name+'-agent.x86_64.qcow2')
  run_cmd([qemu,'convert','-f','raw','-O','qcow2',str(iso_dst),str(qcow)],ROOT)
  info=subprocess.run([qemu,'info','--output=json',str(qcow)],capture_output=True,text=True,check=True)
  if json.loads(info.stdout)['format']!='qcow2' or qcow.stat().st_size==0:die('QCOW2 verification failed')
  for f in review.iterdir():shutil.copy2(f,artifacts/f.name)
  # OCI custom-image archive: image_metadata.json (approved, hash-verified copy) + the qcow2, both at the top level of an uncompressed tar
  meta_json=artifacts/'image_metadata.json';shutil.copy2(review/(name+'-image_metadata.json'),meta_json)
  oci=artifacts/OCI_IMAGE_NAME;oci_tmp=artifacts/(OCI_IMAGE_NAME+'.partial')
  with tarfile.open(str(oci_tmp),'w',format=tarfile.GNU_FORMAT) as t:
   def norm(ti):ti.uid=ti.gid=0;ti.uname=ti.gname='root';ti.mode=0o644;return ti
   t.add(str(meta_json),arcname='image_metadata.json',filter=norm);t.add(str(qcow),arcname=qcow.name,filter=norm)
  oci_tmp.rename(oci)
  with tarfile.open(str(oci)) as t:
   if sorted(t.getnames())!=sorted(['image_metadata.json',qcow.name]):die('OCI archive verification failed: unexpected contents %s'%t.getnames())
  meta_json.unlink()
  m['status']='built';write_json(run/'run.json',m)
  print('BUILT:',artifacts,'\nOCI archive:',oci,'\nNote: OCI image bootability must be tested before production use.')
 except Exception:
  m['status']='build_failed';write_json(run/'run.json',m)
  raise
def archive():
 run=current_run();m=meta(run)
 if m['status']!='built':die('Only successfully built runs can be archived')
 name=m['cluster'];dest=ROOT/'backups'/name/m['run_id']
 if dest.exists():die('Archive destination already exists')
 tmp=dest.with_name(dest.name+'.partial');tmp.mkdir(parents=True)
 try:
  for sub in ('inventory','review','artifacts','generated'):
   if (run/sub).is_dir():shutil.copytree(run/sub,tmp/sub)
  if (run/'approval-diff.txt').is_file():shutil.copy2(run/'approval-diff.txt',tmp/'approval-diff.txt')
  shutil.copy2(run/'run.json',tmp/'run.json')
  for pat in ('preflight-*.log','preflight-*.json'):
   found=sorted((ROOT/'work').glob(pat))
   if found:shutil.copy2(found[-1],tmp/found[-1].name)
  hashes={str(f.relative_to(tmp)):digest(f) for f in tmp.rglob('*') if f.is_file()}
  write_json(tmp/'checksums.json',hashes)
  for rel,h in hashes.items():
   if digest(tmp/rel)!=h:die('Archive verification failed')
  for pth in [tmp,*tmp.rglob('*')]:
   pth.chmod(0o700 if pth.is_dir() else 0o600)
  tmp.rename(dest)
  # Clear only AFTER archive has been verified. Preserve the original run workspace.
  for filename in FILES:shutil.copy2(ROOT/'inventory_templates'/filename,ROOT/'inventory'/filename)
  for filename in TEST_FILES:shutil.copy2(ROOT/'testing_templates'/filename,ROOT/'testing'/filename)
  (ROOT/'work'/'active-run.json').unlink()
  print('ARCHIVED:',dest,'\nInventory and testing settings reset to blank templates. Run workspace preserved:',run)
 except Exception:
  if tmp.exists():shutil.rmtree(tmp)
  raise
def discard(run_id):
 run=current_run();m=meta(run)
 if run_id!=m['run_id']:die('Run ID mismatch')
 (ROOT/'work'/'active-run.json').unlink()
 print('DISCARDED active marker; files preserved at',run)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['preflight','netcheck','prepare','approve','build','archive','discard']);ap.add_argument('--run-id',default='');ap.add_argument('--color',action='store_true');args=ap.parse_args()
 global COLOR;COLOR=args.color
 {'preflight':preflight,'netcheck':netcheck,'prepare':prepare,'approve':lambda:approve(args.run_id),'build':build,'archive':archive,'discard':lambda:discard(args.run_id)}[args.action]()
if __name__=='__main__':
 try:main()
 except Exception as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(1)
