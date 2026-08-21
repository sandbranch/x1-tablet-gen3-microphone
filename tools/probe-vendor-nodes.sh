#!/bin/bash
# Survey ALL Realtek vendor-coefficient nodes, not just nid 0x20.
#
# The realtek driver writes coefs to nids 0x20, 0x53, 0x57, 0x58, 0x5a, 0x1a
# (grep alc_*_coefex_idx).  Our COEF oracle only ever read 0x20.  This dumps
# every candidate bank so we can see which ones are real on the ALC295.
#
#   sudo ./probe-vendor-nodes.sh [label]
#
# Read-only apart from SET_COEF_INDEX, which only selects a register.
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
DEV=/dev/snd/hwC0D0
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="${1:-live}"
OUT="$HERE/vendor-nodes-$LABEL.txt"

live() { hda-verb "$DEV" 0x00 0xf00 0x00 2>/dev/null | awk -F'= ' '/value/{print $2}'; }
[ "$(live)" = "0x10ec0295" ] || { echo "codec not answering"; exit 1; }

# 0x50 and 0x5c added 2026-08-21: the ETW trace shows Windows addressing COEFs on both,
# and 0x5c holds 85 non-zero registers reaching index 0x85 -- past every window we swept.
NIDS="${NIDS:-0x20 0x1a 0x50 0x53 0x57 0x58 0x5a 0x51 0x52 0x54 0x55 0x56 0x59 0x5b 0x5c}"
NREG="${NREG:-32}"

{
  echo "# label $LABEL  date $(date -Is)  kernel $(uname -r)"
  echo "# probe_only $(cut -d, -f1 /sys/module/snd_hda_intel/parameters/probe_only)"
  echo "# NREG=$NREG"
  for nid in $NIDS; do
    echo "--- nid $nid ---"
    for i in $(seq 0 $((NREG-1))); do
      h=$(printf '0x%02x' "$i")
      hda-verb "$DEV" "$nid" SET_COEF_INDEX "$h" >/dev/null 2>&1
      v=$(hda-verb "$DEV" "$nid" GET_PROC_COEF 0x00 2>/dev/null | awk -F'= ' '/value/{print $2}')
      printf '%s %s %s\n' "$nid" "$h" "${v:-ERR}"
    done
  done
} > "$OUT"

[ "$(live)" = "0x10ec0295" ] || echo "!!! CODEC DIED DURING PROBE !!!"
echo "wrote $OUT"
echo
awk '/^--- nid/{nid=$3; nz=0; tot=0; vals=""}
     /^0x/{tot++; if($3!="0x0" && $3!="ERR") nz++; if($3=="ERR") err++}
     /^--- nid/ && NR>1 {}
     END{}' "$OUT" >/dev/null
for nid in $NIDS; do
  tot=$(awk -v n=$nid '$1==n{c++} END{print c+0}' "$OUT")
  nz=$(awk -v n=$nid '$1==n && $3!="0x0" && $3!="ERR"{c++} END{print c+0}' "$OUT")
  err=$(awk -v n=$nid '$1==n && $3=="ERR"{c++} END{print c+0}' "$OUT")
  ff=$(awk -v n=$nid '$1==n && $3=="0xffffffff"{c++} END{print c+0}' "$OUT")
  printf 'nid %-5s  regs=%-3s  nonzero=%-3s  0xffffffff=%-3s  ERR=%s\n' "$nid" "$tot" "$nz" "$ff" "$err"
done
