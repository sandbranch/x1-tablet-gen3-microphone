#!/usr/bin/env python3
"""Read the HDA controller's BAR0 register block via mmap. Read-only, dword accesses."""
import ctypes, mmap, os, sys, time

DEV  = "/sys/bus/pci/devices/0000:00:1f.3"
OUT, LABEL = sys.argv[1], sys.argv[2]
BAR, SIZE = f"{DEV}/resource0", 16384

# --- named controller registers (Intel HD Audio spec) -----------------------
NAMED = {
    0x00:("GCAP/VMIN/VMAJ",4), 0x04:("OUTPAY/INPAY",4), 0x08:("GCTL",4),
    0x0c:("WAKEEN/STATESTS",4), 0x10:("GSTS",4), 0x18:("OUTSTRMPAY/INSTRMPAY",4),
    0x20:("INTCTL",4), 0x24:("INTSTS",4), 0x30:("WALCLK",4), 0x38:("SSYNC",4),
    0x40:("CORBLBASE",4), 0x44:("CORBUBASE",4), 0x48:("CORBWP/CORBRP",4),
    0x4c:("CORBCTL/CORBSTS/CORBSIZE",4), 0x50:("RIRBLBASE",4), 0x54:("RIRBUBASE",4),
    0x58:("RIRBWP/RINTCNT",4), 0x5c:("RIRBCTL/RIRBSTS/RIRBSIZE",4),
    0x60:("ICOI",4), 0x64:("ICII",4), 0x68:("ICIS",4),
    0x70:("DPIBLBASE",4), 0x74:("DPIBUBASE",4),
}
SD_REG = {0x00:"CTL/STS", 0x04:"LPIB", 0x08:"CBL", 0x0c:"LVI/FIFOW",
          0x10:"FIFOSZ/FMT", 0x18:"BDPL", 0x1c:"BDPU"}

def restore(prev):
    try: open(f"{DEV}/power/control","w").write(prev)
    except Exception as e: print("  ! restore failed:", e)

prev = open(f"{DEV}/power/control").read().strip()
print(f"  power/control was '{prev}', runtime_status "
      f"'{open(f'{DEV}/power/runtime_status').read().strip()}'")
open(f"{DEV}/power/control","w").write("on")          # wake it; D3 reads = all-ones
for _ in range(50):
    if open(f"{DEV}/power/runtime_status").read().strip() == "active": break
    time.sleep(0.05)
st = open(f"{DEV}/power/runtime_status").read().strip()
print(f"  forced power/control=on -> runtime_status '{st}'")
if st != "active":
    print("  !! not active, aborting rather than reading D3 MMIO"); restore(prev); sys.exit(1)

passes = []
try:
    fd = os.open(BAR, os.O_RDWR | os.O_SYNC)          # RW map needed for ctypes; we never write
    mm = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    base = ctypes.addressof(ctypes.c_char.from_buffer(mm))
    for p in range(2):                                # two passes -> volatility mask
        passes.append([ctypes.c_uint32.from_address(base + o).value
                       for o in range(0, SIZE, 4)])
        time.sleep(0.20)
finally:
    try:
        del base; mm.close(); os.close(fd)
    except Exception: pass
    restore(prev)
    print(f"  restored power/control='{prev}'")

a, b = passes
if all(v == 0xffffffff for v in a[:16]):
    print("  !! BAR reads all-ones -- device was not really powered. Dump is worthless.")
    sys.exit(1)

volatile = {o*4 for o,(x,y) in enumerate(zip(a,b)) if x != y}
with open(f"{OUT}/bar0-pass1.bin","wb") as f:
    f.write(b"".join(v.to_bytes(4,"little") for v in a))
with open(f"{OUT}/bar0-pass2.bin","wb") as f:
    f.write(b"".join(v.to_bytes(4,"little") for v in b))
with open(f"{OUT}/volatile-offsets.txt","w") as f:
    f.write("# offsets that changed between two back-to-back passes = free-running.\n")
    f.write("# MASK THESE when diffing working vs dead.\n")
    for o in sorted(volatile): f.write(f"0x{o:04x}\n")

def label(o):
    if o in NAMED: return NAMED[o][0]
    if 0x80 <= o < 0x80 + 0x20*16:
        n, r = divmod(o - 0x80, 0x20)
        return f"SD{n}.{SD_REG.get(r,f'+{r:#04x}')}"
    return ""

nz = 0
with open(f"{OUT}/bar0-decoded.txt","w") as f:
    f.write(f"# HDA BAR0 dump, label={LABEL}\n# 'V' = volatile (differs between passes)\n\n")
    for o in range(0, SIZE, 4):
        v = a[o//4]
        if v == 0 and not label(o): continue
        nz += 1
        f.write(f"0x{o:04x}  0x{v:08x}  {'V' if o in volatile else ' '}  {label(o)}\n")
print(f"  {nz} non-zero/named dwords, {len(volatile)} volatile offsets -> {OUT}")
