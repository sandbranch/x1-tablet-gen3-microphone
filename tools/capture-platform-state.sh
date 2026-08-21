#!/bin/bash
# capture-platform-state.sh LABEL
#   Snapshot the whole platform state around the HD-audio controller, to diff
#   working vs dead.  Everything inside the codec is already excluded as an
#   explanation, so this is the remaining surface: pinctrl pad configs, GPIO,
#   PCI config space, clocks, ACPI, power/runtime state.
#
#   Run this FIRST on a cold boot, before anything else touches the machine.
set -uo pipefail
L="${1:?usage: capture-platform-state.sh LABEL}"
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/platform-state-$L"
mkdir -p "$D"

sudo -n bash -s "$D" <<'INNER'
set -uo pipefail
D="$1"
HDA=0000:00:1f.3

lspci -nnvvv                     > "$D/lspci-all.txt"            2>&1
lspci -nnvvv -s $HDA             > "$D/pci-hda.txt"              2>&1
lspci -xxx   -s $HDA             > "$D/pci-hda-configspace.txt"  2>&1
lspci -xxxx  -s $HDA             > "$D/pci-hda-extconfig.txt"    2>&1
lspci -xxxx  -s 00:02.0          > "$D/pci-igpu-extconfig.txt"   2>&1

cat /sys/kernel/debug/gpio       > "$D/gpio-all.txt"             2>&1
cp  /sys/kernel/debug/pinctrl/INT344B:00/pins   "$D/pinctrl-INT344B:00-pins.txt"   2>/dev/null
cp  /sys/kernel/debug/pinctrl/INT344B:00/gpio-ranges   "$D/pinctrl-INT344B:00-ranges.txt"   2>/dev/null
cp  /sys/kernel/debug/pinctrl/INT344B:00/pinconf-pins  "$D/pinctrl-INT344B:00-pinconf.txt"  2>/dev/null
cp  /sys/kernel/debug/pinctrl/INT344B:00/pinmux-pins   "$D/pinctrl-INT344B:00-pinmux.txt"   2>/dev/null

cat /sys/kernel/debug/clk/clk_summary > "$D/clk_summary.txt"     2>&1

cat /proc/asound/card0/codec#0   > "$D/codec-tree.txt"           2>&1
cat /sys/class/sound/card0/device/power/runtime_status > "$D/hda-runtime.txt" 2>&1

{ for f in /sys/bus/pci/devices/$HDA/power/runtime_status \
           /sys/bus/pci/devices/$HDA/power/control \
           /sys/bus/pci/devices/$HDA/power/runtime_suspended_time; do
    printf '%s = %s\n' "$f" "$(cat "$f" 2>/dev/null)"
  done; } > "$D/power.txt" 2>&1

ls /sys/firmware/acpi/tables/    > "$D/acpi-tables.txt"          2>&1
{ for d in /sys/bus/acpi/devices/*; do
    printf '== %s\n' "${d##*/}"; cat "$d/status" 2>/dev/null
  done; } > "$D/acpi-devices.txt" 2>&1
INNER

sudo -n env NREG=160 "$HERE/probe-vendor-nodes.sh" "$L" >/dev/null 2>&1
cp "$HERE"/vendor-nodes-"$L"*.txt "$D/" 2>/dev/null

echo "captured -> $D"
ls -la "$D"
