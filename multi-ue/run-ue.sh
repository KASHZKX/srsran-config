#!/usr/bin/env bash
set -euo pipefail
binary=${1:?srsue binary required}
config=$(realpath "${2:?UE config required}")
route_id=${3:?routing table ID required}
route_script=${4:?routing helper required}
timeout=${UE_ROUTE_TIMEOUT:-90}
[[ $EUID == 0 ]] || { echo "Run this launcher through make ue / make ue2 (sudo)." >&2; exit 1; }
[[ $timeout =~ ^[1-9][0-9]*$ ]] || { echo "UE_ROUTE_TIMEOUT must be positive seconds" >&2; exit 1; }
mapfile -t gw < <(python3 - "$config" <<'PY'
import configparser, sys
c = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
c.read(sys.argv[1])
print(c.get('gw', 'netns'))
print(c.get('gw', 'ip_devname'))
PY
)
[[ ${#gw[@]} == 2 && -n ${gw[0]} && -n ${gw[1]} ]] || exit 1
ns=${gw[0]}
tun=${gw[1]}
# A shared lock avoids make ue and make ue2 racing to create the same namespace.
exec 9>/run/lock/srsran-multi-ue-netns.lock
flock -x 9
if ! ip netns list | awk '{print $1}' | grep -Fxq "$ns"; then
  ip netns add "$ns"
fi
ip -n "$ns" link set lo up
flock -u 9
exec 9>&-
# Keep an existing live UE and its interface intact.
exec 8>"/run/lock/srsran-multi-ue-$ns-$tun.lock"
flock -n 8 || { echo "$ns/$tun is already managed by another UE launcher" >&2; exit 1; }
if ip -n "$ns" link show dev "$tun" >/dev/null 2>&1; then
  echo "$ns/$tun already exists. Stop its old UE before starting this one." >&2
  exit 1
fi
failure=$(mktemp /run/srsran-multi-ue-failure.XXXXXX)
trap 'rm -f "$failure"' EXIT
child=
watcher=
terminate_child() {
  kill -INT "$child" 2>/dev/null || return 0
  for ((i=0;i<30;i++)); do
    kill -0 "$child" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -TERM "$child" 2>/dev/null || true
  for ((i=0;i<20;i++)); do
    kill -0 "$child" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL "$child" 2>/dev/null || true
}
stop_children() {
  trap - INT TERM
  [[ -z $watcher ]] || kill "$watcher" 2>/dev/null || true
  [[ -z $child ]] || terminate_child
}
trap stop_children INT TERM
"$binary" "$config" <&0 &
child=$!
(
  deadline=$((SECONDS + timeout))
  last_ip=
  while kill -0 "$child" 2>/dev/null; do
    current_ip=$(ip -n "$ns" -4 -o addr show dev "$tun" 2>/dev/null |
      awk '{split($4,a,"/");print a[1];exit}' || true)
    if [[ -n $current_ip && $current_ip != "$last_ip" ]]; then
      if ! bash "$route_script" "$ns" "$tun" "$route_id"; then
        echo "Route setup failed for $ns/$tun. Stop the UE and check routing rules." >&2
        echo failed >"$failure"
        terminate_child
        exit 1
      fi
      echo "UE network ready: namespace=$ns TUN=$tun source=$current_ip"
      last_ip=$current_ip
    elif [[ -z $current_ip ]]; then
      last_ip=
      if (( SECONDS >= deadline )); then
        echo "No PDU IPv4 after $timeout seconds. Check NAS/CU-CP logs and make core-check." >&2
        echo "A namespace/default route cannot fix SMF failure or a rejected PDU session." >&2
        echo failed >"$failure"
        terminate_child
        exit 1
      fi
    fi
    [[ -z $current_ip ]] || deadline=$((SECONDS + timeout))
    sleep 1
  done
) &
watcher=$!
status=0
wait "$child" || status=$?
# Preserve watcher errors rather than reporting a successful UE shutdown.
if kill -0 "$watcher" 2>/dev/null; then
  kill "$watcher" 2>/dev/null || true
  wait "$watcher" 2>/dev/null || true
else
  wait "$watcher" || status=1
fi
[[ ! -s $failure ]] || status=1
exit "$status"
