#!/usr/bin/env bash
set -u
[[ $EUID == 0 ]] || { echo "Use make ue-check (sudo required)" >&2; exit 1; }
date -u
echo '=== Namespace interfaces and source routing ==='
ip -n ue1 -4 addr show || exit 1
ip -n ue1 -4 rule show || exit 1
for table in 1001 1002; do
  echo "Routing table $table"
  ip -n ue1 -4 route show table "$table"
done
status=0
for tun in tun_srsue_pdu1 tun_srsue_pdu2; do
  source_ip=$(ip -n ue1 -4 -o addr show dev "$tun" | awk '{split($4,a,"/");print a[1];exit}')
  if [[ -z $source_ip ]]; then
    echo "FAIL $tun has no IPv4"
    status=1
    continue
  fi
  for destination in 8.8.8.8 192.168.56.112; do
    echo "=== $tun source=$source_ip destination=$destination ==="
    ip -n ue1 -4 route get "$destination" from "$source_ip" || status=1
    ip netns exec ue1 ping -n -I "$source_ip" -c 3 -W 2 "$destination" || status=1
  done
  ip -n ue1 -s link show dev "$tun"
done
exit "$status"
