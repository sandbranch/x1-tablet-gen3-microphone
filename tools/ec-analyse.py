#!/usr/bin/env python3
"""EC RAM: which armed-vs-dead byte deltas survive the same-boot volatility floor?"""
"""usage: ec-analyse.py DEAD/ec-ram.txt ARMED/ec-ram.txt VOLATILITY_DIR/"""
import glob, os, re, sys
R = os.path.dirname(os.path.abspath(__file__))

def load(path):
    b = bytearray(256)
    for line in open(path):
        m = re.match(r'^([0-9a-f]{8}):((?: [0-9a-f]{2,4})+)', line)
        if not m: continue
        off = int(m.group(1), 16)
        hexes = m.group(2).split()
        raw = bytes.fromhex(''.join(hexes))
        b[off:off+len(raw)] = raw
    return bytes(b)

dead  = load(sys.argv[1])   # dead-boot ec-ram.txt
armed = load(sys.argv[2])   # armed-boot ec-ram.txt
samples = [armed] + [load(p) for p in sorted(glob.glob(sys.argv[3] + "/ec-*.txt"))]  # same-boot floor

volatile = {i for i in range(256) if len({s[i] for s in samples}) > 1}
delta    = {i for i in range(256) if dead[i] != samples[-1][i]}
stable   = sorted(delta - volatile)

print(f"same-boot armed samples : {len(samples)}")
print(f"bytes differing armed vs dead : {len(delta)}")
print(f"bytes that move on their own within one armed boot : {len(volatile)}")
print(f"\n>>> CANDIDATES (differ armed-vs-dead AND stable across the armed boot): {len(stable)}")
for i in stable:
    print(f"    0x{i:02x}: dead={dead[i]:02x}  armed={armed[i]:02x}"
          f"   (armed-boot samples: {' '.join(f'{s[i]:02x}' for s in samples)})")
print(f"\n--- rejected as EC telemetry (moved during the armed boot): "
      f"{' '.join(f'{i:02x}' for i in sorted(delta & volatile))}")
