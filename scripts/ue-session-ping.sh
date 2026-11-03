#!/usr/bin/env bash
set -euo pipefail

# ==================================================
# Arguments
# ==================================================

ue_ns=${1:?namespace required}
ue_tun=${2:?TUN interface required}
ue_session=${3:?PDU session ID required}

if [[ ! "$ue_session" =~ ^([1-9]|1[0-5])$ ]]; then
  echo "PDU session ID must be 1..15" >&2
  exit 1
fi

# ==================================================
# Get UE IP
# ==================================================

ue_ip=$(
  ip -n "$ue_ns" -4 -o addr show dev "$ue_tun" |
  awk '{split($4, address, "/"); print address[1]; exit}'
)

if [[ -z "$ue_ip" ]]; then
  echo "$ue_tun has no IPv4 address" >&2
  exit 1
fi

# ==================================================
# Ping Test
# ==================================================

echo "Testing PDU Session $ue_session"
echo "Namespace : $ue_ns"
echo "TUN       : $ue_tun"
echo "UE IP     : $ue_ip"

ip netns exec "$ue_ns" \
  ping -I "$ue_ip" -c 5 8.8.8.8