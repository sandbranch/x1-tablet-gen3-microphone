#!/bin/bash
# identify-track.sh [seconds] [label] -- record from the internal DMIC and ask Shazam.
#   Records at the clean 0/63 point, percentile-normalizes (ignores transient clicks),
#   then runs songrec.  Leaves a normalized copy you can play back.
set -uo pipefail
SEC="${1:-25}"; L="${2:-track}"
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
sudo -n bash -c "
  for c in Master Speaker Headphone 'Bass Speaker' PCM; do amixer -c0 -q set \"\$c\" mute 2>/dev/null; done
  amixer -c0 -q set 'Internal Mic Boost' 0; amixer -c0 -q set Capture 63; amixer -c0 -q set Capture cap
  arecord -D hw:0,0 -f S16_LE -r 48000 -c 2 -d $SEC '$HERE/$L.wav'" 2>/dev/null
python3 - "$L" <<'PY'
import wave,sys,numpy as np
L=sys.argv[1]
f=wave.open(f"{L}.wav"); sr=f.getframerate()
x=np.frombuffer(f.readframes(f.getnframes()),'<i2').astype(np.float32).reshape(-1,2)
p=np.percentile(np.abs(x),99.9)                 # ignore transient clicks
g=min(0.89*32767/max(p,1), 60.0)
y=np.clip(x*g,-32768,32767).astype('<i2')
o=wave.open(f"{L}-norm.wav",'wb'); o.setnchannels(2); o.setsampwidth(2); o.setframerate(sr)
o.writeframes(y.tobytes()); o.close()
print(f"  captured {len(x)/sr:.0f}s  p99.9={p:.0f}  gain x{g:.1f}  peak_after={np.abs(y).max()}")
PY
cp "$L-norm.wav" "$HOME/$L-norm.wav"
echo "  --- Shazam (normalized) ---"
timeout 120 songrec audio-file-to-recognized-song "$HOME/$L-norm.wav" 2>/dev/null \
  | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("   no JSON returned"); sys.exit()
t=d.get("track")
if not t: print("   NO MATCH"); sys.exit()
print("   TITLE :",t.get("title")); print("   ARTIST:",t.get("subtitle"))
for s in t.get("sections",[]):
    for m in (s.get("metadata") or []): print("   %-8s: %s"%(m.get("title"),m.get("text")))
'
