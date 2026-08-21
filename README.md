# Internal microphone — ThinkPad X1 Tablet 3rd gen (20KJ / 20KK)

**Status: the microphone works — but only after a warm reboot from Windows.**
There is no native Linux fix yet. This is a research record.

For most of this investigation the internal microphone on this machine recorded nothing
but broadband noise under Linux, at any gain, and the working assumption was a missing
driver enable. On **2026-08-21** the microphone was made to record real audio under Linux
— speech, music, and a commercial track identified correctly by a third-party
fingerprinting service — on an ordinary Linux boot with a stock kernel.

The catch is how that state is reached:

    boot Windows, let it reach the desktop
    warm-reboot into Linux — no power off
    the internal microphone works

Power-cycle the machine and it is dead again. **The state cannot be produced from Linux
alone**, by any means tried: live register writes, reload-time patch firmware, and
cold-boot patch firmware all fail. So this is not yet a fix you can install — it is a
reproducible switch, a large set of eliminations, and a hypothesis.

    machine      ThinkPad X1 Tablet 3rd gen, 20KK / 20KJ
    codec        Realtek ALC295, subsystem 0x17aa2263, revision 0x100002
    controller   Intel Sunrise Point-LP HD Audio, PCI SSID 17aa:2244
    internal mic pin 0x12, config 0x90a60130 = internal, Mic In, connection "Other Digital"

## Reproducing it

1. Boot Windows and let it reach the desktop, so the Realtek driver initialises the codec.
2. **Warm-reboot into Linux.** No power off, no battery pull.
3. Record:

       amixer -c0 set 'Internal Mic Boost' 0
       amixer -c0 set Capture 63
       arecord -D hw:0,0 -f S16_LE -r 48000 -c 2 -d 10 /tmp/mic.wav

Use boost **0**, not the Linux default of 3 — the default applies about +30 dB to this pin
and clips roughly 40 % of samples into a DC rail.

⚠️ **There is no register you can read to tell whether the microphone will work.** On a
boot that came through Windows, `0x20 0x2b` reads `0x181` and the mic works. After an S3
suspend/resume on that same boot, it reads `0x0` — the stock value — **and the mic still
works**. The only reliable test is to record something.

**One Windows boot per *power cycle*, not per reboot.** The state is far more durable
than it first appeared. It survives an S3 suspend, the codec's own D3 power-down, a
`FUNCTION_RESET`, a full PCI remove-and-rescan, **and a warm reboot from Linux back into
Linux with no Windows involved**. Reboot as often as you like; fold the folio shut as often
as you like. Only removing power kills it, and that has been measured, not assumed: on a
cold boot with music playing the capture comes back at rms 25 against 1600–3200 on a
working boot, and the fingerprinting service returns no match.

## How the working state was verified

Every earlier positive result in this project turned out to be an artefact — an internal
loopback recording the machine's own playback, and a mic-boost stage manufacturing a DC
rail. So the confirmation was built to be hard to fool. Output pins were muted for every
capture, and each result was measured against a control.

| test | dead codec | working codec |
|---|---|---|
| speech, analyser-scored | not audio | ✅ real speech at all three gain points |
| music vs silence, paired A/B | +3 % | **19–21×** |
| beat autocorrelation, same music | 0.067 | **0.607** (119.7 BPM) |
| spectral flatness | 0.97 (noise) | 0.29 (tonal) |
| **third-party song identification** | — | ✅ **correct title, artist, album, year** |

The last row is the decisive one. 25 seconds of room audio captured through the internal
microphone was submitted to a commercial acoustic-fingerprinting service, which returned
the correct track. Fingerprint matching depends on precise spectral peak positions and
their timing offsets: noise cannot match, and neither can a microphone with a badly wrong
frequency response. That result establishes the microphone **reproduces** sound, not
merely that something moves when a sound is played.

## What the working state is *not*

With a live working codec it became possible to run the experiment backwards — push
**working → dead** one register at a time and watch for the capture to collapse, instead
of pushing dead → working against registers that refuse to be written. Everything failed
to break it:

- **Static vendor-register state is excluded.** A working-vs-dead diff across all 15
  vendor nodes and 2400 registers, filtered against *two* independent dead samples, left
  17 candidates. Thirteen were forced to their dead values simultaneously and **the
  microphone kept working** — including the `COEF 0x08` analog gate, `0x0c` bit 14, `0x3a`
  and `0x40`. The remaining four were eliminated individually.
- **`0x20 0x2b` is read-only.** It holds `0x181` against an arbitrary write and `0x0` on a
  dead codec against an arbitrary write. It reports internal state; it does not set it.
  It is an *effect*, not a cause — which is why replaying it never worked.
- **nid `0x58` is never touched by Windows** — zero verbs to it in a full 3745-verb boot
  trace of the Windows driver. That bank is hardware amp calibration.
- **The codec tree is identical.** A live working codec versus a cold-boot dead one
  differs by five lines out of 287, all of them caused by the test's own mixer settings.

**Nor is it reachable by any reset software can issue.** The microphone keeps working
through an S3 suspend, through the codec's own **D3** power-down, through a
**`FUNCTION_RESET`**, and through tearing the PCI device out and re-probing the driver from
zero — each of which resets the vendor coefficients to their defaults. Only removing power
from the machine kills it.

And the complete comparison finds nothing: a full 160-register × 15-node dump of a
**working** codec against two **dead** ones — 2400 registers — leaves no register that
separates them. The two *working* states in hand differ from each other more than either
differs from a dead codec.

**Nor is it anywhere else on the platform.** A sixteen-file capture of the entire
surface around the controller — all 152 pinctrl pads with their pad-config registers, GPIO
line state, PCI configuration space at both 256- and 4096-byte depth, the clock tree, the
ACPI table list and every ACPI device's `_STA` — was taken on a working boot and again on a
cold dead one. Everything relevant is **byte-identical**. The only differences are the
camera PMIC's clock and GPIO lines (this tablet's *other* unsupported device, exercised on
one boot and not the other), twenty lines of IRQ-number and PCIe link-training variation,
and three lines of the capture's own mixer settings.

For calibration: two *working* captures differ from each other by five pinctrl RX-level
bits. Working and dead differ by less than working and working.

So the thing Windows leaves behind is not a value that can be read and replayed.

**The decisive demonstration is an S3 suspend/resume.** Across a 12-second `deep` suspend,
every vendor register reverts to its stock value — `0x2b` `0x181`→`0x0`, `0x08`
`0x6a00`→`0x6a8c`, `0x0c` `0x41ef`→`0x1ef`, `0x3a` `0x38`→`0x10`, `0x5c 0x0f` `0x0`→`0x1` —
**and the microphone keeps working**, confirmed by a second correct third-party song
identification and a 5.8× music/silence control.

A cold boot shows stock registers and a dead microphone. A post-resume boot shows stock
registers and a working one. The registers therefore cannot be what distinguishes the two
states: they are symptoms of it. Whatever Windows leaves behind survives a full codec
re-initialisation and dies only on power loss.

## The current hypothesis

That Windows starts a **clock or power domain** — plausibly the PDM/PLL supply for the
digital microphone — which a warm reboot preserves and a power cycle stops.

There is now a concrete address for it. The controller's **memory-mapped** register
block had never been read — `lspci -xxxx` dumps PCI *configuration* space, which is a
different thing — and reading it on a dead boot turns up a five-entry Intel
extended-capability chain including a **Multi-Link** block. Link 0 is the external
HD-audio link carrying the ALC295:

    LCTL @0x0c40+0x04 = 0x00810002    SCF=2, SPA=1, CPA=1

`LCTL.SCF` is the link **clock-frequency select**; `SPA` and `CPA` are the link's requested
and actual power state. That is the first candidate in this investigation shaped like the
answer instead of contradicting it: it lives **in the PCH rather than in the codec**, which
is what a state surviving every codec reset and dying on power removal requires, and unlike
every vendor coefficient chased here, **it is writable**. The working-side dump has not
been taken yet, so this is a hypothesis with an address, not a result — it may come back
empty like the others.

It is the one explanation consistent with every observation: no static replay works; the
registers that correlate are read-only status; the codec tree is unchanged; Windows state
*alone* is insufficient (a boot with the Linux codec driver suppressed, straight off
Windows, is dead — the state is present but nothing has built the capture path); and Linux
init alone is insufficient. Working = Windows' residual state **plus** Linux's own init on
top of it.

Consistent with this, the Windows driver issues **1657 COEF index selects** during boot
where Linux writes **two registers total**, and repeatedly re-selects a small number of
indices — `0x29` 761 times, `0x26` 379 times, `0x2b` 107 times — with no data verb between
them. That is the signature of a poll loop, and `0x2b` is now known to be read-only
status. Windows appears to be waiting on something.

## If you can help

The useful question for someone who knows this silicon: **what starts the digital
microphone's clock domain on an ALC295, and what would preserve it across a warm reboot
but not a power cycle?** A reproducible A/B is available on demand on this machine, which
makes any suggestion cheap to test.

A second, narrower question, for anyone who knows the Intel controller side: **can the
HD-audio Multi-Link `LCTL` state — `SCF`, `SPA`/`CPA` — persist across a warm reset and
account for this?** And is there a reason the link clock select would need to differ for a
PDM microphone hanging off the codec.

## Is this your bug?

    arecord -f S16_LE -r 48000 -c 2 -d 3 /tmp/t.wav

If that gives audible hiss with no speech in it, and:

    cat /proc/asound/card0/codec#0 | head -6      # Realtek ALC295 / 0x17aa2263
    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_COEF_INDEX 0x08
    sudo hda-verb /dev/snd/hwC0D0 0x20 GET_PROC_COEF 0x00
    #   value = 0x6a8c    <- analog input path enabled; this is the noise

then yes.

## Turning the noise off (on a dead boot)

This is **not a fix** — it replaces noise with silence. The hiss is a *floating analog
input*: vendor register `COEF 0x08` bits 2 and 3 gate the codec's analog input path, and
Linux leaves them set on a pin whose only source is digital, so the ADC samples an
unconnected analog input.

    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_COEF_INDEX 0x08
    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_PROC_COEF 0x6a00

Capture then returns exact zeros. This is *not* "what Windows does" — see FINDINGS §5.
It is documented because a microphone that emits hiss into every call is worse than one
that emits nothing, and because it is the cleanest way to confirm the finding yourself.

## This machine is not representative of the ALC295

The same codec with the *same* pin `0x12 = 0x90a60130` config appears in three upstream
ASUS pin quirks whose fixups add nothing at all for the internal mic — the digital
microphone works on other ALC295 machines with zero DMIC-specific code. This is
machine-specific.

## `retracted/`

An earlier version of this release shipped a fix based on `COEF 0x07` bit 10. **That fix
is void** — the register enables an internal DAC→ADC loopback, so the "microphone" was
recording the machine's own playback. It is kept, with a full account of how it passed
review, in [retracted/RETRACTED.md](retracted/RETRACTED.md). Do not install it.

## Prior art

The same symptom is reported and unresolved for this model on Fedora (Discussion #159185)
and on Linux Mint (t=450783, including a second machine in the same thread). Three
independent X1 Tablet Gen 3 machines show it, which rules out a fault in any one unit.
There is no quirk for `17aa:2244` anywhere in the kernel's Realtek codec tree — verified
by grep against the source, not assumed.

Full detail, including corrections and dead ends, in [FINDINGS.md](FINDINGS.md).

## Licence

See [LICENSE](LICENSE).
