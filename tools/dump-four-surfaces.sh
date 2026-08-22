#!/bin/bash
# dump-four-surfaces.sh LABEL
#   The positive-localization dump.  Every prior test was subtractive; this one
#   snapshots the four surfaces that survive S3 and die at S4/S5, so armed and
#   dead can be diffed directly.
#
#   Surface A: ALL FOUR PCH GPIO communities via /dev/mem -- including fdad0000,
#              which is claimed by PNP0C02:00 and NEVER bound by pinctrl.  The 12
#              GPD (deep-sleep-well) pins live only there.  capture-platform-state.sh
#              could not see them, so no "byte-identical" claim ever covered them.
#   Surface B: PMC  (intel_pmc_core debugfs)
#   Surface C: EC RAM (ec_sys, read-only)
#   Surface D: I2C enumeration ONLY -- no blind probing, a scan can hang a bus.
set -uo pipefail
L="${1:?usage: dump-four-surfaces.sh LABEL}"
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/four-surfaces-$L"
mkdir -p "$D"

sudo -n bash -s "$D" "$L" <<'INNER'
set -uo pipefail
D="$1"; L="$2"

# ---- Surface A: all four GPIO communities, raw ----------------------------
python3 - "$D" <<'PY'
import mmap, os, sys
D = sys.argv[1]
COMM = {"comm0_fdac0000":0xfdac0000, "comm1_fdad0000_UNCLAIMED":0xfdad0000,
        "comm2_fdae0000":0xfdae0000, "comm3_fdaf0000":0xfdaf0000}
SIZE = 0x10000
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
for name, base in COMM.items():
    try:
        m = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        blob = m.read(SIZE); m.close()
    except Exception as e:
        open(f"{D}/gpio-{name}.txt","w").write(f"MAP FAILED: {e}\n"); continue
    open(f"{D}/gpio-{name}.bin","wb").write(blob)
    with open(f"{D}/gpio-{name}.txt","w") as f:
        for off in range(0, SIZE, 16):
            row = blob[off:off+16]
            if row == b"\xff"*16 or row == b"\x00"*16:      # keep the file diffable
                continue
            f.write(f"{base+off:08x}: " + " ".join(f"{int.from_bytes(row[i:i+4],'little'):08x}"
                                                   for i in range(0,16,4)) + "\n")
os.close(fd)
PY

# ---- Surface B: PMC -------------------------------------------------------
for f in /sys/kernel/debug/pmc_core/*; do
  [ -f "$f" ] && { printf '== %s\n' "${f##*/}"; cat "$f" 2>&1; }
done > "$D/pmc_core.txt" 2>&1

# ---- Surface C: EC RAM (read-only) ---------------------------------------
modprobe ec_sys write_support=0 2>/dev/null
if [ -r /sys/kernel/debug/ec/ec0/io ]; then
  dd if=/sys/kernel/debug/ec/ec0/io bs=256 count=1 status=none 2>/dev/null \
    | xxd > "$D/ec-ram.txt" 2>&1
else
  echo "EC RAM not readable (ec_sys unavailable)" > "$D/ec-ram.txt"
fi

# ---- Surface D: I2C enumeration only, no probing -------------------------
{ for d in /sys/bus/i2c/devices/*; do
    [ -e "$d/name" ] && printf '%-18s %s\n' "${d##*/}" "$(cat "$d/name" 2>/dev/null)"
  done; } > "$D/i2c-enumeration.txt" 2>&1

# ---- provenance -----------------------------------------------------------
{ echo "label      : $L"; echo "date       : $(date -Is)"; echo "kernel     : $(uname -r)"
  echo "boot id    : $(cat /proc/sys/kernel/random/boot_id)"
  echo "uptime_from: $(uptime -s)"; } > "$D/PROVENANCE.txt"
INNER

md5sum "$D"/*.bin 2>/dev/null > "$D/MD5SUMS.txt"
echo "  wrote $D"
ls -la "$D" | tail -n +2 | awk '{printf "    %-34s %s\n", $9, $5}'
