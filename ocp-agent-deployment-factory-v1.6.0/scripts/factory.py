#!/usr/bin/env python3
"""Inventory-driven OpenShift agent artifacts. No OCI VM provisioning is performed."""
import argparse, concurrent.futures, datetime, hashlib, ipaddress, json, os, re, shutil, subprocess, sys
from pathlib import Path
import importlib.util
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
os.umask(0o077)
ROOT=Path(__file__).resolve().parents[1]
FILES=['cluster.yml','nodes.yml','network.yml','infrastructure.yml','preflight.yml']
def die(s): raise RuntimeError(s)
def load_netcheck():
 spec=importlib.util.spec_from_file_location('netcheck',ROOT/'scripts'/'netcheck.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def env_true(name):return os.environ.get(name,'').strip().lower() in ('1','true','yes')
def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def read_inventory():
 inv={}
 for filename in FILES:
  f=ROOT/'inventory'/filename
  if not f.is_file():die(f'Missing inventory: {f}')
  value=yaml.safe_load(f.read_text())
  if not isinstance(value,dict):die(f'Expected mapping in {filename}')
  inv.update(value)
 return inv
def validate(v):
 c=v['cluster']; n=v['network']; i=v['infrastructure']; hosts=v['nodes']
 if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',str(c['name'])):die('Invalid cluster.name')
 if not re.fullmatch(r'[a-zA-Z0-9.-]+',str(c['base_domain'])) or '.' not in c['base_domain']:die('Invalid base_domain')
 if not str(c['ocp_version']).startswith('4.22'):die('This release is validated for OCP 4.22 only; update compatibility checks before other versions')
 if c['architecture']!='x86_64':die('Only x86_64 currently supported')
 if n['network_type']!='OVNKubernetes':die('OCP 4.22 requires OVNKubernetes')
 if i['platform']!='oci' or i['dns_provider']!='infoblox' or i['loadbalancer_provider']!='f5':die('Supported profile: OCI/Infoblox/F5')
 nets={k:ipaddress.ip_network(str(n[k]),strict=False) for k in ('machine_network','cluster_network','service_network')}
 ks=list(nets)
 for a in range(len(ks)):
  for b in range(a+1,len(ks)):
   if nets[ks[a]].version==nets[ks[b]].version and nets[ks[a]].overlaps(nets[ks[b]]):die(f'{ks[a]} {nets[ks[a]]} overlaps {ks[b]} {nets[ks[b]]}; the three networks must not overlap')
 if not nets['cluster_network'].prefixlen<int(n['host_prefix'])<=32:die(f"host_prefix must be larger than the cluster_network prefix (/{nets['cluster_network'].prefixlen}) and at most 32")
 px=v.get('proxy') or {}
 if px.get('enabled',False):
  if not (px.get('http_proxy') or px.get('https_proxy')):die('proxy.enabled requires http_proxy and/or https_proxy')
  for k in ('http_proxy','https_proxy'):
   if px.get(k) and not re.fullmatch(r'http://\S+',str(px[k])):die(f'proxy.{k} must be an http:// URL (OpenShift supports only http:// proxy URLs)')
  if px.get('additional_trust_bundle_file'):
   tb=Path(px['additional_trust_bundle_file'])
   if not tb.is_file():die(f'Missing proxy.additional_trust_bundle_file: {tb}')
   if '-----BEGIN CERTIFICATE-----' not in tb.read_text():die('proxy.additional_trust_bundle_file must contain a PEM certificate')
  if px.get('additional_trust_bundle_policy','Proxyonly') not in ('Proxyonly','Always'):die('proxy.additional_trust_bundle_policy must be Proxyonly or Always')
 for k in ('rendezvous_ip',):ipaddress.ip_address(c[k])
 for k in ('api_vip','ingress_vip'):ipaddress.ip_address(i[k])
 for ip in i['f5_self_ips']+n['dns_servers']:ipaddress.ip_address(ip)
 if not i['f5_self_ips'] or not n['dns_servers']:die('F5 Self IPs and Infoblox DNS resolvers required')
 if not isinstance(hosts,list) or len(hosts)<3:die('Define at least 3 nodes')
 if sum(x['role']=='master' for x in hosts)!=3:die('Exactly 3 masters required in this supported profile')
 names=set(); ips=set(); macs=set()
 for x in hosts:
  if x['role'] not in ('master','worker'):die('role must be master or worker')
  if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*',x['name']):die('Invalid hostname')
  ipaddress.ip_address(x['ip']);ipaddress.ip_address(x.get('gateway') or n['gateway'])
  if not 1<=int(x['prefix_length'])<=32:die('Invalid prefix_length')
  if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',x['mac']):die('Invalid MAC')
  if x['name'] in names or x['ip'] in ips or x['mac'].lower() in macs:die('Duplicate host name/IP/MAC')
  names.add(x['name']);ips.add(x['ip']);macs.add(x['mac'].lower())
  for dns in x.get('dns_servers') or n['dns_servers']:ipaddress.ip_address(dns)
 if c['rendezvous_ip'] not in {x['ip'] for x in hosts if x['role']=='master'}:die('rendezvous_ip must match a master IP')
 for k in ('pull_secret_file','ssh_public_key_file'):
  if not Path(c[k]).is_file():die(f'Missing {k}: {c[k]}')
 pf=v.get('preflight') or {}
 if pf.get('enabled',True):
  if not isinstance(pf.get('urls'),list) or not pf['urls']:die('preflight.urls must be a non-empty list (or set preflight.enabled: false)')
  if not all(isinstance(u,str) and u.strip() for u in pf['urls']):die('preflight.urls entries must be non-empty strings')
  if int(pf.get('timeout_seconds',10))<1:die('preflight.timeout_seconds must be >= 1')
  if pf.get('ca_bundle') and not Path(pf['ca_bundle']).is_file():die(f"Missing preflight.ca_bundle: {pf['ca_bundle']}")
 load_netcheck().validate_config(v)
 if c.get('release_image') and not re.fullmatch(r'\S+',str(c['release_image'])):die('release_image must not contain whitespace')
 secret=Path(c['pull_secret_file']).read_text().strip();json.loads(secret)
 ssh=Path(c['ssh_public_key_file']).read_text().strip()
 if not ssh.startswith(('ssh-rsa ','ssh-ed25519 ','ecdsa-sha2-')):die('Invalid SSH public key')
 return secret,ssh
def meta(run):return json.loads((run/'run.json').read_text())
def current_run():
 f=ROOT/'work'/'active-run.json'
 if not f.exists():die('No active prepared run; run prepare first')
 return Path(json.loads(f.read_text())['path'])
def write_json(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def proxy_data(v):
 """Return the proxy block for install-config, or None when disabled. noProxy always includes the cluster's own networks."""
 px=v.get('proxy') or {}
 if not px.get('enabled',False):return None
 n=v['network'];c=v['cluster']
 extra=px.get('no_proxy') or []
 if isinstance(extra,str):extra=extra.split(',')
 items=['localhost','127.0.0.1','.svc','.cluster.local',f"api-int.{c['name']}.{c['base_domain']}",str(n['machine_network']),str(n['cluster_network']),str(n['service_network'])]+[x.strip() for x in extra if x and x.strip()]
 no_proxy=','.join(dict.fromkeys(items))
 tb=px.get('additional_trust_bundle_file')
 return {'http_proxy':px.get('http_proxy') or '','https_proxy':px.get('https_proxy') or '','no_proxy':no_proxy,'trust_bundle':Path(tb).read_text().strip() if tb else '','trust_policy':px.get('additional_trust_bundle_policy','Proxyonly')}
def probe_url(curl,url,pf):
 target=url if '://' in url else 'https://'+url
 cmd=[curl,'-sS','-I','-o','/dev/null','-w','%{http_code}','--connect-timeout',str(int(pf.get('timeout_seconds',10))),'--max-time',str(int(pf.get('timeout_seconds',10))),'-L','--max-redirs','3']
 if pf.get('proxy'):cmd+=['-x',pf['proxy']]
 if pf.get('ca_bundle'):cmd+=['--cacert',pf['ca_bundle']]
 r=subprocess.run(cmd+[target],capture_output=True,text=True)
 code=r.stdout.strip()
 ok=r.returncode==0 and code not in ('','000')
 return {'url':target,'ok':ok,'http_code':code,'curl_rc':r.returncode,'detail':'' if ok else (r.stderr.strip() or 'no HTTP response')}
def preflight_check(v):
 """Probe the OCP allowlist URLs. Returns report dict; any HTTP response counts as reachable."""
 pf=v.get('preflight') or {}
 if not pf.get('enabled',True):return {'enabled':False,'results':[]}
 curl=shutil.which('curl')
 if not curl:die('curl not found in PATH; run playbooks/dependencies.yml')
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
  results=list(ex.map(lambda u:probe_url(curl,u,pf),pf['urls']))
 return {'enabled':True,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'proxy':pf.get('proxy') or '','results':results}
def print_report(rep):
 if not rep['enabled']:print('PREFLIGHT: disabled in inventory/preflight.yml');return True
 bad=[r for r in rep['results'] if not r['ok']]
 for r in rep['results']:print('  %-4s %-45s %s'%('OK' if r['ok'] else 'FAIL',r['url'],('HTTP '+r['http_code']) if r['ok'] else r['detail']))
 print('PREFLIGHT: %d/%d URLs reachable'%(len(rep['results'])-len(bad),len(rep['results'])))
 return not bad
def preflight():
 v=read_inventory();validate(v)
 if not print_report(preflight_check(v)):die('Preflight failed: unreachable URLs listed above. Fix firewall/proxy/DNS or update inventory/preflight.yml')
def netcheck():
 v=read_inventory();validate(v);nc=load_netcheck()
 if not nc.print_report(nc.run(v)):die('DNS/F5 checks failed: see FAIL lines above')
def prepare(skip_preflight=False,skip_netcheck=False):
 skip_preflight=skip_preflight or env_true('FACTORY_SKIP_PREFLIGHT');skip_netcheck=skip_netcheck or env_true('FACTORY_SKIP_NETCHECK')
 v=read_inventory();secret,ssh=validate(v);c=v['cluster']; name=c['name']
 active=ROOT/'work'/'active-run.json'
 if active.exists():die('An active run already exists. Finish or explicitly run discard before preparing a new one')
 report={'enabled':False,'skipped':True,'results':[]}
 if skip_preflight:print('PREFLIGHT: skipped (--skip-preflight or FACTORY_SKIP_PREFLIGHT)')
 else:
  report=preflight_check(v)
  if not print_report(report):die('Preflight failed: unreachable URLs listed above. Fix firewall/proxy/DNS, update inventory/preflight.yml, or re-run with -e skip_preflight=true')
 nreport={'enabled':False,'skipped':True,'results':[]}
 if skip_netcheck:print('NETCHECK: skipped (--skip-netcheck or FACTORY_SKIP_NETCHECK)')
 else:
  nc=load_netcheck();nreport=nc.run(v)
  if not nc.print_report(nreport):die('DNS/F5 checks failed: see FAIL lines above. Fix Infoblox/F5, adjust infrastructure.yml, or re-run with -e skip_netcheck=true')
 run_id=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+os.urandom(3).hex()
 run=ROOT/'work'/name/run_id;review=run/'review';installer=run/'installer'
 review.mkdir(parents=True);installer.mkdir()
 env=Environment(loader=FileSystemLoader(str(ROOT/'templates')),undefined=StrictUndefined,keep_trailing_newline=True,trim_blocks=True,lstrip_blocks=True)
 data=dict(v,proxy_cfg=proxy_data(v),pull_secret_json=secret,ssh_public_key=ssh,masters_count=3,workers_count=sum(x['role']=='worker' for x in v['nodes']))
 for src,out in [('install-config.yaml.j2','install-config.yaml'),('agent-config.yaml.j2','agent-config.yaml')]:
  rendered=env.get_template(src).render(**data)
  yaml.safe_load(rendered)
  (installer/out).write_text(rendered)
  (review/(name+'-'+out)).write_text(rendered)
 # Record inventory snapshot and validate it cannot be altered unnoticed
 (run/'inventory').mkdir()
 for f in FILES:shutil.copy2(ROOT/'inventory'/f,run/'inventory'/f)
 checks={f:digest(review/f) for f in sorted(x.name for x in review.iterdir())}
 write_json(run/'run.json',{'cluster':name,'run_id':run_id,'version':c['ocp_version'],'status':'awaiting_approval','checksums':checks,'inventory_checksums':{f:digest(run/'inventory'/f) for f in FILES}})
 write_json(run/'preflight-report.json',report)
 write_json(run/'netcheck-report.json',nreport)
 write_json(active,{'path':str(run)})
 print('PREPARED:',run,'\nReview:',review,'\nRun: python3 scripts/factory.py approve --run-id',run_id)
def approve(run_id):
 run=current_run();m=meta(run)
 if run_id!=m['run_id']:die('Run ID mismatch')
 if m['status']!='awaiting_approval':die('Run not awaiting approval')
 for f,h in m['checksums'].items():
  if digest(run/'review'/f)!=h:die('Review artifact changed: regenerate from inventory')
 for f,h in m['inventory_checksums'].items():
  if digest(ROOT/'inventory'/f)!=h:die('Inventory changed since prepare; discard and prepare again')
 for f in FILES:
  if digest(run/'inventory'/f)!=m['inventory_checksums'][f]:die('Inventory snapshot modified')
 m['status']='approved';m['approved_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();m['approved_by']=os.environ.get('USER','unknown')
 write_json(run/'run.json',m);print('APPROVED',run)
def run_cmd(cmd,cwd,env=None):
 print('RUN:', ' '.join(cmd),flush=True)
 subprocess.run(cmd,cwd=cwd,check=True,env=env)
def build():
 run=current_run();m=meta(run)
 if m['status'] not in ('approved','build_failed'):die('Run is not approved')
 name=m['cluster']; installer=run/'installer';review=run/'review'
 for f,h in m['checksums'].items():
  if digest(review/f)!=h:die('Reviewed file changed; approval invalid')
  standard=f[len(name)+1:]
  if m['status']=='approved' and digest(installer/standard)!=h:die('Installer file changed; approval invalid')
 for f,h in m['inventory_checksums'].items():
  if digest(ROOT/'inventory'/f)!=h or digest(run/'inventory'/f)!=h:die('Inventory changed; approval invalid')
 if m['status']=='build_failed':
  # openshift-install consumes install-config.yaml/agent-config.yaml, so restore them from the approved, hash-verified review copies
  shutil.rmtree(installer,ignore_errors=True);installer.mkdir()
  for f in m['checksums']:shutil.copy2(review/f,installer/f[len(name)+1:])
 try:
  installer_bin=shutil.which('openshift-install');qemu=shutil.which('qemu-img')
  if not installer_bin or not qemu:die('openshift-install and qemu-img must be installed in PATH')
  version=subprocess.run([installer_bin,'version'],capture_output=True,text=True,check=True).stdout
  if m['version'] not in version:die(f'Installer version mismatch: expected {m["version"]}; got {version.strip()}')
  env=dict(os.environ)
  rel=(read_inventory()['cluster'].get('release_image') or '').strip()
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
  m['status']='built';write_json(run/'run.json',m)
  print('BUILT:',artifacts,'\nNote: OCI image bootability must be tested before production use.')
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
  for sub in ('inventory','review','artifacts'):
   shutil.copytree(run/sub,tmp/sub)
  shutil.copy2(run/'run.json',tmp/'run.json')
  for extra in ('preflight-report.json','netcheck-report.json'):
   if (run/extra).is_file():shutil.copy2(run/extra,tmp/extra)
  hashes={str(f.relative_to(tmp)):digest(f) for f in tmp.rglob('*') if f.is_file()}
  write_json(tmp/'checksums.json',hashes)
  for rel,h in hashes.items():
   if digest(tmp/rel)!=h:die('Archive verification failed')
  tmp.rename(dest)
  # Clear only AFTER archive has been verified. Preserve the original run workspace.
  for filename in FILES:shutil.copy2(ROOT/'inventory_templates'/filename,ROOT/'inventory'/filename)
  (ROOT/'work'/'active-run.json').unlink()
  print('ARCHIVED:',dest,'\nInventory reset to blank templates. Run workspace preserved:',run)
 except Exception:
  if tmp.exists():shutil.rmtree(tmp)
  raise
def discard(run_id):
 run=current_run();m=meta(run)
 if run_id!=m['run_id']:die('Run ID mismatch')
 (ROOT/'work'/'active-run.json').unlink()
 print('DISCARDED active marker; files preserved at',run)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['preflight','netcheck','prepare','approve','build','archive','discard']);ap.add_argument('--run-id',default='');ap.add_argument('--skip-preflight',action='store_true');ap.add_argument('--skip-netcheck',action='store_true');args=ap.parse_args()
 {'preflight':preflight,'netcheck':netcheck,'prepare':lambda:prepare(args.skip_preflight,args.skip_netcheck),'approve':lambda:approve(args.run_id),'build':build,'archive':archive,'discard':lambda:discard(args.run_id)}[args.action]()
if __name__=='__main__':
 try:main()
 except Exception as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(1)
