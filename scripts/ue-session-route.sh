#!/usr/bin/env bash
set -euo pipefail
ue_ns=${1:?namespace required}
ue_tun=${2:?TUN interface required}
ue_session=${3:?routing slot required}
[[ $ue_session =~ ^([1-9]|1[0-5])$ ]] || { echo "Routing slot must be 1..15" >&2; exit 1; }
[[ $ue_ns =~ ^[a-zA-Z0-9_.-]+$ ]] || exit 1
exec 9>"/run/lock/srsue-route-$ue_ns-$ue_session.lock"
flock -x 9
python3 - "$ue_ns" "$ue_tun" "$((1000 + ue_session))" <<'PY'
import ipaddress, json, shlex, subprocess, sys
ns, tun, table_s = sys.argv[1:]
table = int(table_s)
prefix = ['ip', '-n', ns, '-4']
def command(args, json_output=False, missing_table=False):
    argv = prefix + args
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode:
        if missing_table and 'FIB table does not exist' in result.stderr:
            return []
        raise RuntimeError(shlex.join(argv) + ': ' + result.stderr.strip())
    return json.loads(result.stdout or '[]') if json_output else result.stdout
def rules():
    return command(['-j', 'rule', 'show'], True)
def defaults():
    return command(['-j', 'route', 'show', 'table', table_s, 'default'], True, True)
try:
    addresses = command(['-j', 'addr', 'show', 'dev', tun], True)
    ips = [a['local'] for link in addresses for a in link.get('addr_info', [])
           if a.get('family') == 'inet']
    if len(ips) != 1:
        raise RuntimeError(tun + ' must have exactly one IPv4 address')
    source = ips[0]
    owned = [r for r in rules() if r.get('priority') == table]
    for rule in owned:
        extra = set(rule) - {'priority', 'src', 'srclen', 'table', 'action', 'flags', 'protocol'}
        try:
            network = ipaddress.ip_network(rule.get('src', '0.0.0.0/0'), strict=False)
        except ValueError:
            network = None
        if (str(rule.get('table')) != table_s or extra or network is None
                or network.prefixlen != 32 or rule.get('srclen', 32) != 32):
            raise RuntimeError('Priority ' + table_s + ' has a foreign rule: ' + str(rule))
    routes = defaults()
    exact = (len(routes) == 1 and routes[0].get('dev') == tun
             and routes[0].get('prefsrc') == source
             and not routes[0].get('gateway')
             and routes[0].get('type', 'unicast') == 'unicast')
    if not exact:
        command(['route', 'replace', 'default', 'dev', tun, 'src', source, 'table', table_s])
    exact_rule = (len(owned) == 1
                  and str(ipaddress.ip_network(owned[0]['src'], strict=False).network_address) == source)
    if not exact_rule:
        for rule in owned:
            command(['rule', 'del', 'priority', table_s, 'from', rule['src'], 'table', table_s])
        command(['rule', 'add', 'priority', table_s, 'from', source + '/32', 'table', table_s])
    print('Routing slot ' + str(table - 1000) + ' configured: ' + source
          + ' -> ' + tun + ', table ' + table_s)
except (RuntimeError, ValueError, KeyError) as error:
    print('UE route setup failed: ' + str(error), file=sys.stderr)
    for args in (['addr', 'show', 'dev', tun], ['rule', 'show'],
                 ['route', 'show', 'table', table_s]):
        result = subprocess.run(prefix + args, text=True, capture_output=True)
        print(shlex.join(prefix + args), file=sys.stderr)
        print(result.stdout + result.stderr, file=sys.stderr)
    sys.exit(1)
PY
