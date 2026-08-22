#!/usr/bin/env python3
"""replay-corb.py -- replay the Windows CORB burst into the ALC295 IN ORDER.

The static values from this burst are already negative twice over
(stock-oracle-validated-replay-negative, corrected-coef-sweep-negative).  What has
never been tried is the SEQUENCE: the same verbs, in the order Windows issued them,
with the GET_PROC_COEF read-backs left in place, interleaved with the pin/amp/power
verbs that bracket them.

Source: audio/windows-trip-2026-08-22/results/corb-entries-A.txt -- the complete
unwrapped post-restart burst (CORBWP=0x91, ring churn 0 verbs in 25 s).

Chronological order in a 256-entry ring with WP=145 is 146..255 then 0..145.

Encoding (matches the kernel's make_codec_cmd):
    cmd = cad<<28 | nid<<20 | verb<<8 | parm
  long verb  (bits[19:16] == 0x7 or 0xf): verb = 12 bits, parm = 8 bits
  short verb (anything else)            : verb = nibble<<8, parm = 16 bits

SAFETY: aborts if the burst would write COEF 0x2d, or COEF 0x33 with bit 15 set --
the two registers that brick this codec and need a full power cycle to recover
(coef-2d-kills-the-codec, coef-33-bit15-kills-the-codec).
"""
import subprocess, sys, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "..", "windows-trip-2026-08-22", "results", "corb-entries-A.txt")
DEV  = "/dev/snd/hwC0D0"
WP   = 0x91

LONG = {0x701:"SET_CONNECT_SEL", 0x703:"SET_PROC_STATE", 0x704:"SET_SDI_SELECT",
        0x705:"SET_POWER_STATE", 0x706:"SET_CHANNEL_STREAMID",
        0x707:"SET_PIN_WIDGET_CONTROL", 0x708:"SET_UNSOLICITED_ENABLE",
        0x709:"SET_PIN_SENSE", 0x70c:"SET_EAPD_BTLENABLE", 0x70d:"SET_DIGI_CONVERT_1",
        0x70e:"SET_DIGI_CONVERT_2", 0x715:"SET_GPIO_DATA", 0x716:"SET_GPIO_MASK",
        0x717:"SET_GPIO_DIRECTION", 0x718:"SET_GPIO_WAKE_MASK",
        0x71c:"SET_CONFIG_DEFAULT_0", 0x71d:"SET_CONFIG_DEFAULT_1",
        0x71e:"SET_CONFIG_DEFAULT_2", 0x71f:"SET_CONFIG_DEFAULT_3",
        0x7ff:"SET_CODEC_RESET",
        0xf00:"GET_PARAMETERS", 0xf01:"GET_CONNECT_SEL", 0xf02:"GET_CONNECT_LIST",
        0xf03:"GET_PROC_STATE", 0xf05:"GET_POWER_STATE", 0xf06:"GET_CONV",
        0xf07:"GET_PIN_WIDGET_CONTROL", 0xf08:"GET_UNSOLICITED_RESPONSE",
        0xf09:"GET_PIN_SENSE", 0xf0c:"GET_EAPD_BTLENABLE", 0xf0d:"GET_DIGI_CONVERT_1",
        0xf15:"GET_GPIO_DATA", 0xf16:"GET_GPIO_MASK", 0xf17:"GET_GPIO_DIRECTION",
        0xf1c:"GET_CONFIG_DEFAULT"}
SHORT = {0x200:"SET_CONVERTER_FORMAT", 0x300:"SET_AMP_GAIN_MUTE",
         0x400:"SET_PROC_COEF", 0x500:"SET_COEF_INDEX",
         0xa00:"GET_CONVERTER_FORMAT", 0xb00:"GET_AMP_GAIN_MUTE",
         0xc00:"GET_PROC_COEF", 0xd00:"GET_COEF_INDEX"}

def decode(cmd):
    nid = (cmd >> 20) & 0xff
    p20 = cmd & 0xfffff
    nib = (p20 >> 16) & 0xf
    if nib in (0x7, 0xf):
        verb, parm = (p20 >> 8) & 0xfff, p20 & 0xff
        name = LONG.get(verb, f"verb_{verb:03x}")
    else:
        verb, parm = nib << 8, p20 & 0xffff
        name = SHORT.get(verb, f"verb_{verb:03x}")
    return nid, verb, parm, name

def load():
    raw = {}
    for line in open(SRC, encoding="utf-8-sig"):
        m = re.match(r"\s*(\d{3})\s+(0x[0-9a-fA-F]{8})", line)
        if m: raw[int(m.group(1))] = int(m.group(2), 16)
    order = list(range(WP + 1, 256)) + list(range(0, WP + 1))
    return [(i, raw[i]) for i in order if i in raw]

def safety(seq):
    idx, bad = {}, []
    for i, cmd in seq:
        nid, verb, parm, _ = decode(cmd)
        if verb == 0x500: idx[nid] = parm
        elif verb == 0x400:
            c = idx.get(nid)
            if c == 0x2d:
                bad.append(f"entry {i}: nid 0x{nid:02x} COEF 0x2d = 0x{parm:04x}  (BRICK)")
            if c == 0x33 and (parm & 0x8000):
                bad.append(f"entry {i}: nid 0x{nid:02x} COEF 0x33 = 0x{parm:04x}  bit15 (BRICK)")
    return bad

def main():
    go = "--go" in sys.argv
    seq = load()
    bad = safety(seq)
    print(f"loaded {len(seq)} verbs, chronological (entry {seq[0][0]} .. {seq[-1][0]})")
    if bad:
        print("!! BRICK REGISTER IN THE BURST -- REFUSING TO REPLAY"); [print("  "+b) for b in bad]
        sys.exit(2)
    print("safety scan: no COEF 0x2d write, no COEF 0x33 bit-15 write.  Safe to replay.")

    kinds = {}
    for _, cmd in seq:
        kinds[decode(cmd)[3]] = kinds.get(decode(cmd)[3], 0) + 1
    print("verb histogram: " + ", ".join(f"{k}x{v}" for k, v in
          sorted(kinds.items(), key=lambda kv: -kv[1])))
    if not go:
        print("\n(dry run -- pass --go to actually send)")
        for i, cmd in seq:
            nid, verb, parm, name = decode(cmd)
            print(f"  [{i:3d}] 0x{cmd:08x}  nid 0x{nid:02x}  {name:24s} 0x{parm:04x}")
        return

    log = open(os.path.join(HERE, "replay-corb.log"), "w")
    log.write(f"=== ordered CORB replay {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    sent = 0
    for i, cmd in seq:
        nid, verb, parm, name = decode(cmd)
        r = subprocess.run(["hda-verb", DEV, f"0x{nid:02x}", f"0x{verb:03x}", f"0x{parm:04x}"],
                           capture_output=True, text=True)
        m = re.search(r"value\s*=\s*(0x[0-9a-fA-F]+)", r.stdout)
        resp = m.group(1) if m else (r.stdout.strip().replace("\n", " ") or r.stderr.strip())
        log.write(f"[{i:3d}] 0x{cmd:08x} nid 0x{nid:02x} {name:24s} 0x{parm:04x} -> {resp}\n")
        sent += 1
    log.close()
    print(f"sent {sent} verbs in order -> replay-corb.log")

main()
