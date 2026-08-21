#!/bin/bash
# dump-hda-mmio.sh LABEL
#   Dump the HD-audio controller's MMIO/BAR0 register block (16 KiB) -- the one
#   surface capture-platform-state.sh does NOT cover ("lspci -xxxx" is PCI config
#   space only).
#
#   Reads via mmap on /sys/bus/pci/devices/.../resource0.
#   🚨 NEVER use /dev/mem on this box -- it hard-hangs it.
#   🚨 BAR4 (64 KiB) is the Intel cAVS DSP aperture. Reading it while the DSP
#      power domain is gated can hang the machine. This script does NOT touch it.
#
#   The controller runtime-suspends when idle; MMIO reads in D3 return all-ones.
#   So we force power/control=on for the dump and restore it afterwards.
#   ⚠️ Take the working-side dump the SAME way or the diff is meaningless.
#
#   Two back-to-back passes are taken so free-running registers (WALCLK, stream
#   LPIB, counters) identify themselves as volatile -- that is the diff mask.
set -uo pipefail
L="${1:?usage: dump-hda-mmio.sh LABEL}"
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/hda-mmio-$L"; mkdir -p "$D"
sudo -n python3 "$HERE/hda_mmio.py" "$D" "$L"
