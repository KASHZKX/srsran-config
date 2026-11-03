#!/usr/bin/env bash
set -euo pipefail

ue_ns=${1:?namespace required}
ue_tun=${2:?TUN interface required}
ue_session=${3:?PDU session ID required}

if [[ ! "$ue_session" =~ ^([1-9]|1[0-5])$ ]]; then
  echo "PDU session ID must be 1..15" >&2
  exit 1
fi

# 取得 TUN 的 IPv4
ue_ip=$(ip -n "$ue_ns" -4 -o addr show dev "$ue_tun" |
  awk '{split($4, address, "/"); print address[1]; exit}')

if [[ -z "$ue_ip" ]]; then
  echo "TUN $ue_tun has no IPv4 address" >&2
  exit 1
fi

# 每個 PDU Session 使用獨立 Routing Table
ue_table=$((1000 + ue_session))

# 建立或更新路由
ip -n "$ue_ns" -4 route replace default \
  dev "$ue_tun" \
  src "$ue_ip" \
  table "$ue_table"

# 清理此 Session 專用 Priority 的舊規則
# 前提：1001~1015 已保留給此路由管理腳本
while ip -n "$ue_ns" -4 rule show |
  grep -qE "^[[:space:]]*${ue_table}:"; do
  ip -n "$ue_ns" -4 rule del priority "$ue_table"
done

# 建立新的 Source-based Rule
ip -n "$ue_ns" -4 rule add \
  priority "$ue_table" \
  from "$ue_ip/32" \
  table "$ue_table"

echo "PDU $ue_session route configured"
echo "  TUN: $ue_tun"
echo "  UE IP: $ue_ip"
echo "  Table: $ue_table"