#!/usr/bin/env python3
"""Owned, reversible network setup for the RMF Slice 2 experiment.

Run with sudo. No service is started here. The existing PDU2 session is required.
The root-owned journal contains exact undo commands, not a full firewall restore.
"""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

POOL = ipaddress.ip_network('10.60.128.0/17')
MEC = '192.168.56.112'
EDGE = '192.168.56.114'
NS = 'ue1'
TUN = 'tun_srsue_pdu2'
HOST_IF = 'rmfs2-host'
UE_IF = 'rmfs2-ue'
HOST = '172.31.252.1'
PEER = '172.31.252.2'
PORT = '22011'
GATEWAY_PORT = '22012'
STATE_DIR = Path('/run/rmf-slice2')


class SetupError(RuntimeError):
    pass


def run(argv, check=True):
    result = subprocess.run(argv, text=True, capture_output=True)
    if check and result.returncode:
        raise SetupError(f'{shlex.join(argv)}: {result.stderr.strip()}')
    return result


def ip(*args, ns=False):
    return ['ip', *(['-n', NS] if ns else []), *args]


def fw(*args, ns=False):
    return [*(['ip', 'netns', 'exec', NS] if ns else []),
            'iptables', '-w', '5', *args]


def read_json(argv):
    return json.loads(run(argv).stdout or '[]')


def pdu_ip():
    data = read_json(ip('-j', '-4', 'addr', 'show', 'dev', TUN, ns=True))
    addresses = [a['local'] for link in data for a in link.get('addr_info', [])
                 if a.get('family') == 'inet']
    if len(addresses) != 1 or ipaddress.ip_address(addresses[0]) not in POOL:
        raise SetupError('PDU2 must have exactly one current IPv4 address in '
                         f'{POOL}; establish the session first')
    return addresses[0]


def save(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)


def change(path, state, command, undo):
    # Persist before mutation so an interrupted run remains recoverable.
    state['undo'].append(undo)
    save(path, state)
    run(command)


def remove(path, state):
    errors = []
    for commands in reversed(state['undo']):
        for command in commands:
            result = run(command, check=False)
            # "already absent" is harmless after an interrupted setup.
            absent = ('does not exist', 'No such', 'Cannot find', 'Bad rule',
                      'No chain/target/match', 'not found')
            if result.returncode and not any(x in result.stderr for x in absent):
                errors.append(f'{shlex.join(command)}: {result.stderr.strip()}')
    if errors:
        raise SetupError('Cleanup incomplete; journal retained:\n' + '\n'.join(errors))
    path.unlink(missing_ok=True)


def unused_link(name, ns=False):
    if run(ip('link', 'show', 'dev', name, ns=ns), check=False).returncode == 0:
        raise SetupError(f'Interface {name} already exists without this journal')


def address_conflicts():
    linknet = ipaddress.ip_network(HOST + '/30', strict=False)
    for ns in (False, True):
        for item in read_json(ip('-j', '-4', 'addr', 'show', ns=ns)):
            for addr in item.get('addr_info', []):
                existing = ipaddress.ip_network(
                    f"{addr['local']}/{addr['prefixlen']}", strict=False)
                if linknet.overlaps(existing):
                    raise SetupError(f'{linknet} overlaps existing address {existing}')
        for route in read_json(ip('-j', '-4', 'route', 'show', 'table', 'all', ns=ns)):
            dst = route.get('dst', 'default')
            if dst != 'default' and linknet.overlaps(ipaddress.ip_network(dst, strict=False)):
                raise SetupError(f'{linknet} overlaps existing route {dst}')


def chain(path, state, table, name, hook, rules, ns=False):
    if run(fw('-t', table, '-S', name, ns=ns), check=False).returncode == 0:
        raise SetupError(f'Firewall chain {name} already exists without this journal')
    change(path, state, fw('-t', table, '-N', name, ns=ns),
           [fw('-t', table, '-F', name, ns=ns),
            fw('-t', table, '-X', name, ns=ns)])
    for rule in rules:
        run(fw('-t', table, '-A', name, *rule, ns=ns))
    change(path, state, fw('-t', table, '-I', hook, '1', '-j', name, ns=ns),
           [fw('-t', table, '-D', hook, '-j', name, ns=ns)])


def set_sysctl(path, state, key, value):
    prefix = ['ip', 'netns', 'exec', NS, 'sysctl']
    previous = run([*prefix, '-n', key]).stdout.strip()
    if previous != str(value):
        change(path, state, [*prefix, '-qw', f'{key}={value}'],
               [[*prefix, '-qw', f'{key}={previous}']])


def setup_gateway(path, state, current):
    port = GATEWAY_PORT
    chain(path, state, 'nat', 'RMF_S2_GW_DNAT', 'PREROUTING', [[
        '-i', TUN, '-s', MEC + '/32', '-d', current + '/32',
        '-p', 'tcp', '--dport', port, '-j', 'DNAT',
        '--to-destination', HOST + ':' + port]], ns=True)
    chain(path, state, 'nat', 'RMF_S2_GW_SNAT', 'POSTROUTING', [[
        '-o', UE_IF, '-s', MEC + '/32', '-d', HOST + '/32',
        '-p', 'tcp', '--dport', port, '-m', 'conntrack', '--ctstate', 'DNAT',
        '-j', 'SNAT', '--to-source', PEER]], ns=True)
    # This chain runs before the base chain's catch-all veth drop.
    chain(path, state, 'filter', 'RMF_S2_GW_FWD', 'FORWARD', [
        ['-i', TUN, '-o', UE_IF, '-s', MEC + '/32', '-d', HOST + '/32',
         '-p', 'tcp', '--dport', port, '-m', 'conntrack', '--ctstate',
         'DNAT', '-j', 'ACCEPT'],
        ['-i', UE_IF, '-o', TUN, '-s', HOST + '/32', '-d', MEC + '/32',
         '-p', 'tcp', '--sport', port, '-m', 'conntrack', '--ctstate',
         'ESTABLISHED', '-j', 'ACCEPT'],
    ], ns=True)
    chain(path, state, 'filter', 'RMF_S2_GW_HOST', 'INPUT', [
        ['-i', HOST_IF, '-s', PEER + '/32', '-d', HOST + '/32',
         '-p', 'tcp', '--dport', port, '-j', 'ACCEPT'],
        ['-p', 'tcp', '--dport', port, '-j', 'REJECT', '--reject-with', 'tcp-reset'],
    ])
    state['ready'] = True
    save(path, state)


def gateway_status(state, current):
    if not state.get('ready') or state['pdu_ip'] != current:
        raise SetupError('Gateway setup is stale; run gateway-down, then gateway-up')
    for table, hook, name, ns in (
            ('nat', 'PREROUTING', 'RMF_S2_GW_DNAT', True),
            ('nat', 'POSTROUTING', 'RMF_S2_GW_SNAT', True),
            ('filter', 'FORWARD', 'RMF_S2_GW_FWD', True),
            ('filter', 'INPUT', 'RMF_S2_GW_HOST', False)):
        run(fw('-t', table, '-C', hook, '-j', name, ns=ns))
    print(json.dumps({'role': 'ue-gateway', 'pdu_ip': current,
                      'bind_ip': HOST, 'port': int(GATEWAY_PORT), 'ready': True}))


def setup_ue(path, state):
    current = pdu_ip()
    unused_link(HOST_IF)
    unused_link(UE_IF, ns=True)
    address_conflicts()
    rules = read_json(ip('-j', '-4', 'rule', 'show', ns=True))
    if any(r.get('priority') in (1102, 1103) for r in rules):
        raise SetupError('Policy priorities 1102/1103 are already in use')
    state['pdu_ip'] = current
    state['iptables_version'] = run(['iptables', '--version']).stdout.strip()
    save(path, state)

    # Back up the exact session-owned table/priority before reusing its helper.
    old_routes = run(ip('-4', 'route', 'show', 'table', '1002', ns=True),
                     check=False).stdout.splitlines()
    old_rules = [line.split(':', 1)[1].strip()
                 for line in run(ip('-4', 'rule', 'show', ns=True)).stdout.splitlines()
                 if line.split(':', 1)[0].strip() == '1002']
    # Delete only the rule this helper installs, then restore the previous state.
    restore = [
        ip('-4', 'rule', 'del', 'priority', '1002', 'from', current + '/32',
           'table', '1002', ns=True),
        ip('-4', 'route', 'flush', 'table', '1002', ns=True),
        *[ip('-4', 'route', 'add', 'table', '1002', *shlex.split(line), ns=True)
          for line in old_routes],
        *[ip('-4', 'rule', 'add', 'priority', '1002', *shlex.split(line), ns=True)
          for line in old_rules],
    ]
    helper = Path(__file__).with_name('ue-session-route.sh')
    if not helper.is_file():
        raise SetupError(f'Missing existing session helper: {helper}')
    change(path, state, ['bash', str(helper), NS, TUN, '2'], restore)

    change(path, state,
           ip('link', 'add', HOST_IF, 'type', 'veth', 'peer', 'name', UE_IF),
           [ip('link', 'del', HOST_IF)])
    run(ip('link', 'set', UE_IF, 'netns', NS))
    run(ip('addr', 'add', HOST + '/30', 'dev', HOST_IF))
    run(ip('addr', 'add', PEER + '/30', 'dev', UE_IF, ns=True))
    run(ip('link', 'set', HOST_IF, 'up'))
    run(ip('link', 'set', UE_IF, 'up', ns=True))
    for key in ('net.ipv4.ip_forward',):
        set_sysctl(path, state, key, 1)
    for iface in ('all', TUN, UE_IF):
        set_sysctl(path, state, f'net.ipv4.conf.{iface}.rp_filter', 2)

    for priority, tail in (
            ('1102', ['lookup', '1002']),
            ('1103', ['prohibit'])):
        rule = ['priority', priority, 'from', HOST + '/32', 'to', MEC + '/32', *tail]
        change(path, state, ip('-4', 'rule', 'add', *rule, ns=True),
               [ip('-4', 'rule', 'del', *rule, ns=True)])

    chain(path, state, 'nat', 'RMF_S2_DNAT', 'PREROUTING', [[
        '-i', TUN, '-s', MEC + '/32', '-d', current + '/32',
        '-p', 'tcp', '--dport', PORT, '-j', 'DNAT',
        '--to-destination', HOST + ':' + PORT]], ns=True)
    chain(path, state, 'nat', 'RMF_S2_SNAT', 'POSTROUTING', [[
        '-o', UE_IF, '-s', MEC + '/32', '-d', HOST + '/32',
        '-p', 'tcp', '--dport', PORT, '-m', 'conntrack', '--ctstate', 'DNAT',
        '-j', 'SNAT', '--to-source', PEER]], ns=True)
    chain(path, state, 'filter', 'RMF_S2_FORWARD', 'FORWARD', [
        ['-i', TUN, '-o', UE_IF, '-s', MEC + '/32', '-d', HOST + '/32',
         '-p', 'tcp', '--dport', PORT, '-m', 'conntrack',
         '--ctstate', 'NEW,ESTABLISHED', '-j', 'ACCEPT'],
        ['-i', UE_IF, '-o', TUN, '-s', HOST + '/32', '-d', MEC + '/32',
         '-p', 'tcp', '--sport', PORT, '-m', 'conntrack',
         '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT'],
        ['-i', UE_IF, '-j', 'DROP'],
        ['-o', UE_IF, '-j', 'DROP'],
        ['-i', TUN, '-p', 'tcp', '--dport', PORT, '-j', 'DROP'],
    ], ns=True)
    # Local readiness uses loopback routing; only the namespace veth may enter FM.
    chain(path, state, 'filter', 'RMF_S2_HOST', 'INPUT', [
        ['-i', 'lo', '-d', HOST + '/32', '-p', 'tcp', '--dport', PORT, '-j', 'ACCEPT'],
        ['-i', HOST_IF, '-s', PEER + '/32', '-d', HOST + '/32',
         '-p', 'tcp', '--dport', PORT, '-j', 'ACCEPT'],
        ['-p', 'tcp', '--dport', PORT, '-j', 'REJECT', '--reject-with', 'tcp-reset'],
    ])
    state['ready'] = True
    save(path, state)


def setup_server(path, state):
    addresses = read_json(ip('-j', '-4', 'addr', 'show', 'dev', 'enp0s8'))
    if not any(a['local'] == MEC for link in addresses for a in link.get('addr_info', [])):
        raise SetupError(f'enp0s8 must own {MEC}')
    existing = run(ip('-4', 'route', 'show', 'exact', str(POOL))).stdout.strip()
    if existing:
        raise SetupError(f'Existing UE-pool route must be reviewed first: {existing}')
    route = [str(POOL), 'via', EDGE, 'dev', 'enp0s8', 'src', MEC, 'proto', '186']
    change(path, state, ip('-4', 'route', 'add', *route),
           [ip('-4', 'route', 'del', *route)])
    state['ready'] = True
    save(path, state)


def status(state):
    if not state.get('ready'):
        raise SetupError('Incomplete setup; run down before applying again')
    if state['role'] == 'ue':
        current = pdu_ip()
        if current != state['pdu_ip']:
            raise SetupError('PDU2 IP changed; stop RMF, run down, then up and regenerate config')
        for table, name, hook, ns in (
            ('nat', 'RMF_S2_DNAT', 'PREROUTING', True),
            ('nat', 'RMF_S2_SNAT', 'POSTROUTING', True),
            ('filter', 'RMF_S2_FORWARD', 'FORWARD', True),
            ('filter', 'RMF_S2_HOST', 'INPUT', False),
        ):
            run(fw('-t', table, '-C', hook, '-j', name, ns=ns))
        for name, ns in ((HOST_IF, False), (UE_IF, True)):
            run(ip('link', 'show', 'dev', name, ns=ns))
        reply = read_json(ip('-j', '-4', 'route', 'get', MEC, 'from', HOST,
                             'iif', UE_IF, ns=True))
        if not reply or reply[0].get('dev') != TUN:
            raise SetupError('NAT reply does not route over PDU2')
        print(json.dumps({'role': 'ue', 'pdu_ip': current,
                          'bind_ip': HOST, 'port': int(PORT), 'ready': True}))
    else:
        route = read_json(ip('-j', '-4', 'route', 'get', str(POOL.network_address + 1)))
        if not route or route[0].get('gateway') != EDGE or route[0].get('prefsrc') != MEC:
            raise SetupError('Server route no longer uses edge and MEC source')
        print(json.dumps({'role': 'server', 'gateway': EDGE, 'source': MEC, 'ready': True}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('ue', 'server'))
    parser.add_argument('action', choices=(
        'up', 'status', 'down', 'gateway-up', 'gateway-status', 'gateway-down'))
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Use sudo for network operations and the root-owned journal')
    if args.action.startswith('gateway-') and args.role != 'ue':
        parser.error('The gateway extension is installed only on UE')
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE_DIR / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = STATE_DIR / (args.role + '.json')
        state = json.loads(path.read_text()) if path.exists() else None
        gateway_path = STATE_DIR / 'ue-gateway.json'
        gateway = json.loads(gateway_path.read_text()) if gateway_path.exists() else None
        if args.role == 'ue' and args.action in ('down', 'gateway-down'):
            if gateway:
                remove(gateway_path, gateway)
            if args.action == 'gateway-down':
                print('Owned RMF Slice 2 gateway rules removed')
                return 0
        if args.action in ('gateway-up', 'gateway-status'):
            if not state:
                raise SetupError('Run ue up before enabling the gateway')
            status(state)
            current = state['pdu_ip']
            if gateway:
                gateway_status(gateway, current)
            elif args.action == 'gateway-status':
                raise SetupError('No gateway journal; run gateway-up first')
            else:
                gateway = {'pdu_ip': current, 'ready': False, 'undo': []}
                try:
                    setup_gateway(gateway_path, gateway, current)
                    gateway_status(gateway, current)
                except Exception:
                    if gateway_path.exists():
                        remove(gateway_path, gateway)
                    raise
            return 0
        if args.action == 'down':
            if state:
                remove(path, state)
            print('Owned RMF Slice 2 setup removed')
        elif args.action == 'status' or state:
            if not state:
                raise SetupError('No setup journal; run up first')
            status(state)
        else:
            state = {'role': args.role, 'ready': False, 'undo': []}
            try:
                (setup_ue if args.role == 'ue' else setup_server)(path, state)
                status(state)
            except Exception:
                if path.exists():
                    remove(path, state)
                raise
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (SetupError, OSError, ValueError) as error:
        print(f'RMF Slice 2: {error}', file=sys.stderr)
        raise SystemExit(1)
