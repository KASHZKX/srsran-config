import json, os, pathlib, subprocess, tempfile
base=pathlib.Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='multi-ue-test-') as tmp:
 p=pathlib.Path(tmp)
 runner=p/'run.sh'
 runner.write_text((base/'run-ue.sh').read_text().replace('[[ $EUID == 0 ]]','true').replace('/run/lock/',tmp+'/').replace('/run/srsran-',tmp+'/srsran-'))
 (p/'ue.conf').write_text('[gw]\nnetns=ue1\nip_devname=tun_srsue_pdu1\n')
 (p/'ip').write_text("""#!/bin/bash
echo "ip $*" >>"$TEST_ROOT/events"
if [[ $1 == netns && $2 == list ]]; then
 [[ ! -f $TEST_ROOT/ns ]] || echo ue1
elif [[ $1 == netns && $2 == add ]]; then
 touch "$TEST_ROOT/ns"
elif [[ $* == *"addr show"* ]]; then
 [[ ! -f $TEST_ROOT/tun ]] || echo '3: tun_srsue_pdu1 inet 10.60.0.1/32 scope global tun_srsue_pdu1'
elif [[ $* == *"link show"* ]]; then
 [[ -f $TEST_ROOT/tun ]]
fi
""")
 (p/'fake-ue').write_text("""#!/bin/bash
trap 'exit 0' TERM
[[ $TEST_MODE == no-pdu ]] || touch "$TEST_ROOT/tun"
if [[ $TEST_MODE == ready ]]; then sleep 3; exit 0; fi
while true; do sleep 0.1; done
""")
 (p/'route').write_text('#!/bin/bash\necho "route $*" >>"$TEST_ROOT/events"\n[[ $TEST_MODE != routefail ]]\n')
 for name in ('ip','fake-ue','route'):(p/name).chmod(0o755)
 env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],TEST_ROOT=tmp,UE_ROUTE_TIMEOUT='2')
 def run(mode):
  env['TEST_MODE']=mode
  return subprocess.run(['bash',str(runner),str(p/'fake-ue'),str(p/'ue.conf'),'1',str(p/'route')],env=env,capture_output=True,text=True,timeout=15)
 result=run('ready')
 assert result.returncode==0,(result.stdout,result.stderr)
 events=(p/'events').read_text()
 assert 'ip netns add ue1' in events and 'route ue1 tun_srsue_pdu1 1' in events,events
 print('PASS namespace creation and automatic source-route setup',flush=True)
 result=run('ready')
 assert result.returncode!=0 and 'already exists' in result.stderr,result
 print('PASS existing interface is protected',flush=True)
 (p/'tun').unlink()
 result=run('no-pdu')
 assert result.returncode!=0 and 'No PDU IPv4' in result.stderr,result
 print('PASS no PDU IPv4 returns failure and terminates child',flush=True)
 result=run('routefail')
 assert result.returncode!=0 and 'Route setup failed' in result.stderr,result
 print('PASS route failure returns failure and terminates child',flush=True)
 core=p/'core.sh'
 core.write_text((base/'core-session.sh').read_text().replace('/tmp/srsran-multi-ue-core-reset.lock',tmp+'/core.lock'))
 (p/'microk8s').write_text("""#!/usr/bin/env python3
import json,os,pathlib,sys
p=pathlib.Path(os.environ['TEST_ROOT']); a=sys.argv[1:]
def stamp(nf):
 return ('2026-11-17T18:40:00Z' if nf=='smf' else '2026-11-17T18:41:00Z') if (p/(nf+'-reset')).exists() else ('2026-11-17T18:33:00Z' if nf=='smf' else '2026-11-17T17:00:00Z')
if 'get' in a:
 nf=a[a.index('-l')+1].split('=')[1]
 if a[-1]=='name':print('pod/'+nf+'-old')
 else:print(json.dumps({'items':[{'metadata':{'name':nf+'-new'},'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}],'containerStatuses':[{'name':nf,'state':{'running':{'startedAt':stamp(nf)}}}]}}]}))
elif 'delete' in a:
 nf=a[a.index('delete')+1].split('/')[1].split('-')[0]
 (p/(nf+'-reset')).touch()
 with (p/'core-events').open('a') as f:f.write(nf+'\\n')
elif 'logs' in a:
 for last in (241,242,243,245):print(f'Received PFCP Association Setup Accepted Response from UPF[10.100.50.{last}]')
else:sys.exit(2)
""")
 (p/'microk8s').chmod(0o755)
 result=subprocess.run(['bash',str(core),'check'],env=env,capture_output=True,text=True)
 assert result.returncode!=0 and 'SMF restarted after AMF' in result.stderr,result
 print('PASS stale Core context is detected',flush=True)
 result=subprocess.run(['bash',str(core),'reset'],env=env,capture_output=True,text=True)
 assert result.returncode==0,(result.stdout,result.stderr)
 assert (p/'core-events').read_text()=='smf\namf\n'
 print('PASS Core reset order and ready/PFCP checks',flush=True)
