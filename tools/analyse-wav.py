#!/usr/bin/env python3
"""Judge a capture against the instrument rules this project learned the hard way.

  analyse-wav.py FILE.wav [--drop 0.5]

Applies every trap check from the mic lane:
  * drops the head transient (start transients faked a hit once)
  * requires SUSTAINED frame RMS, not a burst
  * rejects Nyquist alternation (stuck converter emitting DC)
  * rejects single-stuck-value and tiny distinct-count
  * rejects bit-identical channels (DC discharge, loopback)
  * rejects monotonic decay to zero (discharge transient)
  * reports band energies and spectral spread for the flat-noise-vs-acoustics call
"""
import sys, wave, numpy as np

def load(path):
    w = wave.open(path, 'rb')
    n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    raw = w.readframes(n); w.close()
    dt = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    a = np.frombuffer(raw, dtype=dt).astype(np.float64)
    if sw == 1: a -= 128
    return a.reshape(-1, ch), sr, sw

def main():
    path = sys.argv[1]
    drop = 0.5
    if '--drop' in sys.argv: drop = float(sys.argv[sys.argv.index('--drop')+1])
    a, sr, sw = load(path)
    print(f"{path}: {a.shape[0]/sr:.2f}s  {a.shape[1]}ch  {sr} Hz")
    a = a[int(drop*sr):]
    if a.shape[0] < sr//2:
        print("  TOO SHORT after drop"); return
    verdicts = []
    for c in range(a.shape[1]):
        x = a[:, c]
        # clipping is measured against the FORMAT's full scale, not the file's own
        # max -- otherwise a silent file "clips" at its own +/-6 LSB noise floor
        full = {1: 127.0, 2: 32767.0, 4: 2147483647.0}[sw]
        peak = np.abs(x).max()
        clip = 100.0*(np.abs(x) >= 0.99*full).mean()
        dc = x.mean()
        x = x - dc                      # DC leaks into the 50-300 band and skews every ratio
        rms = np.sqrt((x**2).mean()); dist = len(np.unique(x))
        # frame RMS
        fl = sr//2
        fr = np.array([np.sqrt((x[i:i+fl]**2).mean()) for i in range(0, len(x)-fl, fl)])
        mod = fr.max()/max(fr.min(), 1e-9)
        # nyquist alternation: energy concentrated at fs/2
        sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        fq = np.fft.rfftfreq(len(x), 1/sr)
        nyq_frac = sp[-len(sp)//50:].sum()/max(sp.sum(), 1e-9)
        # monotonic decay
        decay = bool(len(fr) > 3 and np.all(np.diff(fr) <= 1e-9) and fr[-1] < 0.1*max(fr[0],1e-9))
        bands = [(50,300),(300,1000),(1000,3000),(3000,6000),(6000,10000),(10000,20000)]
        be = []
        tot = max((sp**2).sum(), 1e-9)
        for lo,hi in bands:
            m = (fq>=lo)&(fq<hi); be.append(100*(sp[m]**2).sum()/tot)
        spread = max(be)/max(min(be), 1e-9)
        # --- speech-envelope test -------------------------------------------------
        # A low-pitched voice puts most of its energy under 300 Hz, so band ratios
        # alone reject real speech (they did, on the L6 point-1 calibration).  Judge
        # the 300-3400 Hz envelope instead: speech alternates burst and pause.
        F = np.fft.rfft(x); F[(fq < 300) | (fq > 3400)] = 0
        vb = np.fft.irfft(F, n=len(x))
        fl2 = max(int(0.02*sr), 1)
        nb = len(vb)//fl2
        env = np.array([vb[i*fl2:(i+1)*fl2].std() for i in range(nb)]) if nb else np.zeros(1)
        floor = np.percentile(env, 10)
        active = float((env > max(4*floor, 1e-9)).mean())     # fraction of frames "loud"
        vb_rms = vb.std()
        vb_dyn = env.max()/max(floor, 1e-9)
        # the voiceband must carry a real SHARE of the signal, not merely exist: a
        # clipped DC-dominated loopback (lb-0x0200) leaves a tiny 0.3-3.4k residual
        # with big dynamic range and would otherwise pass.
        vb_share = vb_rms/max(rms, 1e-9)
        speechy = (vb_rms > 20 and vb_share > 0.05
                   and 0.10 <= active <= 0.90 and vb_dyn > 8)
        print(f"  ch{c}: rms={rms:8.1f} peak={peak:7.0f} distinct={dist:6d} frameRMS {fr.min():.0f}..{fr.max():.0f} mod={mod:.2f}")
        print(f"        bands 50-300/.3-1k/1-3k/3-6k/6-10k/10-20k = " +
              " ".join(f"{v:5.1f}%" for v in be) + f"   spread={spread:.1f}x")
        print(f"        dc={dc:+.1f} clip={clip:.1f}%  voiceband(0.3-3.4k) rms={vb_rms:.1f} "
              f"share={100*vb_share:.0f}% active={100*active:.0f}% dyn={vb_dyn:.1f}x  "
              f"speech-envelope={'YES' if speechy else 'no'}")
        flags = []
        if dist <= 4: flags.append("STUCK(few distinct values)")
        if nyq_frac > 0.5: flags.append("NYQUIST-CONCENTRATED(stuck converter)")
        if decay: flags.append("MONOTONIC-DECAY(discharge transient)")
        if mod < 1.5: flags.append("NO-MODULATION(stationary noise)")
        if rms < 1: flags.append("SILENT")
        if clip > 1: flags.append(f"CLIPPING({clip:.1f}% of samples at full scale)")
        verdicts.append((rms, mod, flags, be, speechy))
        if flags: print(f"        ⚠ {'; '.join(flags)}")
    if a.shape[1] == 2:
        same = np.array_equal(a[:,0], a[:,1])
        print(f"  channels bit-identical: {same}" + ("   ⚠ suspicious" if same else ""))
    # overall
    rms, mod, flags, be, speechy = verdicts[0]
    fatal = [f for f in flags if not f.startswith("CLIPPING")]
    if rms < 1:
        print("  VERDICT: EXACT SILENCE")
    elif fatal:
        print(f"  VERDICT: NOT AUDIO — {fatal[0]}")
    elif speechy:
        print("  VERDICT: ✅ LOOKS LIKE REAL SPEECH (modulated, voice-band envelope)")
    else:
        print("  VERDICT: data present but not speech-shaped — inspect")
    if any(f.startswith("CLIPPING") for f in flags):
        print("  NOTE: input is clipping — lower the capture gain before trusting levels")

main()
