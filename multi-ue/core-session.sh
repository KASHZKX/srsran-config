#!/usr/bin/env bash
# This script runs on the Core VM, under the normal MicroK8s operator account.
set -euo pipefail
action=${1:-check}
[[ $action == check || $action == reset ]] || { echo "Usage: $0 check|reset" >&2; exit 2; }
command -v microk8s >/dev/null || { echo "Run core-session.sh on the Core VM through make core-check/core-reset" >&2; exit 1; }
k() { microk8s kubectl -n free5gc "$@"; }
ready() {
  k get pods -l "nf=$1" -o json | python3 -c '
import json,sys
items=[p for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")]
ok=[p for p in items if p["status"].get("phase")=="Running"
    and any(c["type"]=="Ready" and c["status"]=="True" for c in p["status"].get("conditions",[]))]
if len(items)!=1 or len(ok)!=1: sys.exit(1)
p=ok[0]; s=next(s for s in p["status"]["containerStatuses"] if s["name"]==sys.argv[1])
print(p["metadata"]["name"],s["state"]["running"]["startedAt"])
' "$1"
}
associations() {
  local log ip
  log=$(k logs "$1" -c smf --tail=-1 2>&1)
  for ip in 241 242 243 245; do
    grep -F "Received PFCP Association Setup Accepted Response from UPF[10.100.50.$ip]" <<<"$log" >/dev/null || return 1
  done
}
if [[ $action == reset ]]; then
  exec 9>/tmp/srsran-multi-ue-core-reset.lock
  flock -n 9 || { echo "Another Core reset is running" >&2; exit 1; }
  echo "Resetting SMF then AMF. Existing UE sessions will need registration again."
  for nf in smf amf; do
    mapfile -t pods < <(k get pods -l "nf=$nf" -o name)
    [[ ${#pods[@]} == 1 ]] || { echo "Expected one $nf pod, found ${#pods[@]}; refusing reset" >&2; exit 1; }
    k delete "${pods[0]}" --wait=true --timeout=60s
    state=
    for ((n=0;n<60;n++)); do
      state=$(ready "$nf" 2>/dev/null) && break
      sleep 2
    done
    [[ -n $state ]] || { echo "$nf did not become ready" >&2; exit 1; }
    if [[ $nf == smf ]]; then
      pod=${state%% *}
      good=false
      for ((n=0;n<30;n++)); do
        if associations "$pod"; then good=true; break; fi
        sleep 2
      done
      $good || { echo "SMF PFCP associations incomplete; AMF was not restarted" >&2; exit 1; }
    fi
  done
fi
smf=$(ready smf) || { echo "SMF is not ready" >&2; exit 1; }
amf=$(ready amf) || { echo "AMF is not ready" >&2; exit 1; }
associations "${smf%% *}" || { echo "Cannot verify all four PFCP associations; inspect SMF logs" >&2; exit 1; }
if [[ ${smf#* } > ${amf#* } ]]; then
  echo "SMF restarted after AMF. AMF may retain invalid SM contexts. Run make core-reset before UE registration." >&2
  exit 1
fi
echo "Core session check passed"
echo "SMF $smf"
echo "AMF $amf"
