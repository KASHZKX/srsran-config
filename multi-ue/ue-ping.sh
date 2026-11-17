#!/usr/bin/env bash
set -euo pipefail
tun=${1:?TUN required}
destination=${2:?destination required}
source_ip=$(ip -n ue1 -4 -o addr show dev "$tun" | awk '{split($4,a,"/");print a[1];exit}')
[[ -n $source_ip ]] || { echo "$tun has no PDU IPv4" >&2; exit 1; }
ip netns exec ue1 ip -4 route get "$destination" from "$source_ip"
exec ip netns exec ue1 ping -I "$source_ip" -c 4 "$destination"
