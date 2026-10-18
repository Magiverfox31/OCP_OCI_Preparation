#!/usr/bin/env python3
"""Inventory-driven OpenShift agent artifacts. No OCI VM provisioning is performed."""
import argparse, datetime, hashlib, ipaddress, json, os, re, shutil, subprocess, sys
from pathlib import Path
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
os.umask(0o077)
ROOT=Path(__file__).resolve().parents[1]
FILES=['cluster.yml','nodes.yml','network.yml','infrastructure.yml']
def die(s): raise RuntimeError(s)
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
 if not str(c['ocp_version']).startswith('4.22'):die('This v1.3 release is validated for OCP 4.22 only; update compatibility checks before other versions')
 if c['architecture']!='x86_64':die('Only x86_64 currently supported')
 if n['network_type']!='OVNKubernetes':die('OCP 4.22 requires OVNKubernetes')
 if i['platform']!='oci' or i['dns_provider']!='infoblox' or i['loadbalancer_provider']!='f5':die('Supported profile: OCI/Infoblox/F5')
 for k in ('machine_network','cluster_network','service_network'):ipaddress.ip_network(n[k],strict=False)
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
def prepare():
 v=read_inventory();secret,ssh=validate(v);c=v['cluster']; name=c['name']
 active=ROOT/'work'/'active-run.json'
 if active.exists():die('An active run already exists. Finish or explicitly run discard before preparing a new one')
 run_id=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+os.urandom(3).hex()
 run=ROOT/'work'/name/run_id;review=run/'review';installer=run/'installer'
 review.mkdir(parents=True);installer.mkdir()
 env=Environment(loader=FileSystemLoader(str(ROOT/'templates')),undefined=StrictUndefined,keep_trailing_newline=True)
 data=dict(v,pull_secret_json=secret,ssh_public_key=ssh,masters_count=3)
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
def run_cmd(cmd,cwd):
 print('RUN:', ' '.join(cmd),flush=True)
 subprocess.run(cmd,cwd=cwd,check=True)
def build():
 run=current_run();m=meta(run)
 if m['status'] not in ('approved','build_failed'):die('Run is not approved')
 name=m['cluster']; installer=run/'installer';review=run/'review'
 for f,h in m['checksums'].items():
  if digest(review/f)!=h:die('Reviewed file changed; approval invalid')
  standard=f[len(name)+1:]
  if digest(installer/standard)!=h:die('Installer file changed; approval invalid')
 for f,h in m['inventory_checksums'].items():
  if digest(ROOT/'inventory'/f)!=h or digest(run/'inventory'/f)!=h:die('Inventory changed; approval invalid')
 try:
  installer_bin=shutil.which('openshift-install');qemu=shutil.which('qemu-img')
  if not installer_bin or not qemu:die('openshift-install and qemu-img must be installed in PATH')
  version=subprocess.run([installer_bin,'version'],capture_output=True,text=True,check=True).stdout
  if m['version'] not in version:die(f'Installer version mismatch: expected {m["version"]}; got {version.strip()}')
  run_cmd([installer_bin,'agent','create','image','--dir',str(installer)],ROOT)
  iso=installer/'agent.x86_64.iso'
  if not iso.is_file() or iso.stat().st_size==0:die('Installer did not create a nonempty agent.x86_64.iso')
  artifacts=run/'artifacts';artifacts.mkdir(exist_ok=True)
  iso_dst=artifacts/(name+'-agent.x86_64.iso');shutil.copy2(iso,iso_dst)
  qcow=artifacts/(name+'-agent.x86_64.qcow2')
  run_cmd([qemu,'convert','-f','raw','-O','qcow2',str(iso_dst),str(qcow)],ROOT)
  info=subprocess.run([qemu,'info','--output=json',str(qcow)],capture_output=True,text=True,check=True)
  if json.loads(info)['format']!='qcow2' or qcow.stat().st_size==0:die('QCOW2 verification failed')
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
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','approve','build','archive','discard']);ap.add_argument('--run-id',default='');args=ap.parse_args()
 {'prepare':prepare,'approve':lambda:approve(args.run_id),'build':build,'archive':archive,'discard':lambda:discard(args.run_id)}[args.action]()
if __name__=='__main__':
 try:main()
 except Exception as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(1)
