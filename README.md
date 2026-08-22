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

## What is left

Every surface this project could read has now been read on a working boot and a dead one,
and they are the same. The list is worth stating plainly so nobody repeats it:

| surface | result |
|---|---|
| ~2400 codec registers, all 8 vendor COEF banks | nothing separates working from dead |
| codec verbs as static state **and** replayed in Windows' exact order | negative |
| the codec tree / topology | identical |
| 152 pinctrl pads, PCI config space, ACPI, the clock tree | identical |
| the full 16 KiB HD-audio controller **BAR0**, including `LCTL`/`SCF` and `PPCTL` | **identical** |
| the **DSP** — resident state and its loaded libraries | survives a full core reset ⇒ excluded |
| all four PCH **GPIO communities**, including the deep-well GPD pads pinctrl never binds | identical |
| the **PMC**, the **EC**, I²C enumeration | identical, or explained as charger telemetry |
| firmware / BIOS / ME acting on their own | excluded — disabling the Windows audio stack kills it |
| a slowly-decaying rail or stored charge | excluded — 30 seconds without power is enough |

An earlier version of this README proposed the HD-audio Multi-Link `LCTL.SCF` link clock as
the answer. **That is now measured and negative**: `SCF` is 2 on a working boot, a dead boot,
and under Windows. The whole 16 KiB register block is byte-identical between working and
dead. Kept here rather than quietly deleted, because which way the evidence pointed before
it was tested is part of the record.

Four things *are* established:

1. **The audio arrives over the HD-audio link from the codec — not over the SoC's PDM/DMIC
   interface.** Windows' own DSP pipeline, decoded from an IPC trace of a live capture, uses
   gateway type `HDA_LINK_INPUT`, not `DMIC_LINK_INPUT`. Both operating systems pull this
   microphone through the ALC295. Linux even does it with the DSP processing pipe globally
   disabled. This kills the "the PDM interface is unarmed" reading that a lot of this
   investigation assumed.
2. **The Realtek codec function driver `RTKVHD64.sys` is necessary.** Disable only it in
   Windows, leave the controller and DSP running, warm-reboot — dead. Disable the whole
   controller — also dead.
3. **But its codec verbs are not the mechanism.** All 256 CORB entries from a Windows boot,
   replayed in true ring order with the read-backs in place and the resulting state verified
   still live afterwards, leave the microphone dead.
4. **The state lives in a power domain kept across S3 and lost at S4/S5.** It survives
   suspend, D3, `FUNCTION_RESET`, a full PCI re-probe, a DSP core reset, and Linux→Linux warm
   reboots. Hibernation kills it, and so does 30 seconds unplugged.

So: something that survives a complete codec re-initialisation *and* a complete DSP reset,
persists across warm reboots indefinitely, dies within seconds of power removal — and is
invisible in every register on the platform that Linux can read.

## If you can help

This is published because it is stuck, not because it is solved. A **switchable A/B is
available on demand** on this machine — boot Windows, warm reboot, the microphone works;
power-cycle, it does not — which makes any suggestion cheap to test, and results come back
the same day. Concrete questions, most useful first:

1. **What can `RTKVHD64.sys` do to an ALC295 that is not a codec verb and not DSP-resident
   state?** It is necessary, its verbs are excluded, and the DSP has been reset out from
   under a working state without killing it. On this platform the codec enumerates on the
   SST bus (`INTELAUDIO\FUNC_01`), so the driver also speaks DSP IPC — but the libraries it
   loads are demonstrably not the mechanism. What other channel is there?

2. **Is there state on an ALC295 that is not addressable through the verb or COEF
   interfaces, and that clears only on VDD loss?** Everything observed fits a latch inside
   the codec that the documented interfaces cannot read back. If that exists, this whole
   investigation has been looking at the wrong side of the link.

3. **For the Intel controller side:** with `PPCTL` = 0 and the DSP pipe disabled, the legacy
   `snd_hda_intel` path captures real audio from this microphone on a warm boot and silence
   on a cold one, with byte-identical controller registers. What differs that a register
   dump would not show?

4. **Has anyone seen this shape before** — a device that a Windows boot arms for the rest of
   the power cycle, across arbitrary warm reboots, with no readable state difference? The
   shape may be more familiar to someone than the specific silicon.

If you want to test something, the tools are in [tools/](tools/): platform and MMIO capture,
the four deep-well surfaces, the SST/IPC decoder, the CORB replayer, and the capture
analyser that scores a recording against a control instead of trusting it.

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
