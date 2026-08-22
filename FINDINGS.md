# Findings

Research record for the internal microphone of the ThinkPad X1 Tablet 3rd gen
(20KJ / 20KK), Realtek ALC295, HDA controller `17aa:2244`. Kernel 7.0, Ubuntu.

The bug is **not solved.** This documents what is established, what is excluded, and what
is left — including results that were published here and later corrected or retracted.
The negative results are the point as much as the positive ones: several of them close off
whole methods, and two of them invalidate measurements that looked clean at the time.

> **⭐ Read [§11](#11--2026-08-21--the-microphone-works-on-a-windows-warm-reboot) first.**
> On 2026-08-21 the microphone was made to record real audio under Linux — verified by
> third-party song identification — by warm-rebooting from Windows. It still cannot be
> switched on from Linux alone. §11 also **excludes static vendor-register state and the
> codec tree entirely**, which supersedes the framing of several sections below: §6's
> replay results and §10's "what is left" are now closed questions, not open ones.

---

## 0. Corrections to the initial release

Five claims in the first version of this document were wrong or wrongly scoped. Each is
corrected in place below; they are collected here because how they failed is reusable.

**C1 — "Windows clears the analog gate because it reads the mic digitally." Wrong.**
All Windows register values had been sampled after the vendor driver ran its shutdown
path. Read *during* an active Windows capture, `COEF 0x08` is `0x6a0c` — bits 2+3 **set**,
analog path **open**. Windows clears them only on teardown. See §5.
*Reusable lesson: a warm reboot into another OS reads the codec as the previous driver
**left** it, not as it **used** it. That is a different measurement, and nothing
distinguishes the two from inside the dump.*

**C2 — `0x3a` and `0x40` were never settings.** They were in the 14-register Windows
delta, and they were the two that most stubbornly refused live writes, which made them
look important. Live, mid-capture, they hold the **Linux** value; the `0x3e`/`0x88f0` we
chased are written by Windows' *shutdown* path. Target list 14 → 12.

**C3 — "Static COEF state is excluded" was scoped to one register bank out of eight.**
`alc_read_coef_idx()`/`alc_write_coef_idx()` are macros that hardcode nid `0x20`. The
Realtek driver addresses vendor coefficients on six nodes, and our codec's own init path
(`alc225_init` → `alc285_hp_init`) writes nids `0x57` and `0x58`. Probing live, seven
banks besides `0x20` hold real, distinct, non-zero state (`0x53 0x54 0x56 0x57 0x58 0x5a
0x5b`). Every "COEF space is exhausted" statement in the initial release means
*nid-`0x20` space*. See §10.

**C4 — the ADC `0x07` routing story is a real mechanism, but it is not the fault.**
§2 correctly describes the generic parser dropping ADC `0x07`. It does not follow that
this is the bug: the working ASUS ALC295 machines have an active pin `0x19` too, so the
parser drops ADC `0x07` for them in exactly the same way — and their internal mic works,
through mixer `0x23` into ADC `0x08`. The codec decimates the PDM and presents it to the
analog mixer. **The stock ADC-`0x08` path is the one that matches a proven-working
configuration**; the pin-`0x19`-disabled/ADC-`0x07` oracle tests a path no working machine
uses.

**C5 — "a 76 MB ETW trace showed zero HDA verb traffic": right observation, wrong
conclusion.** That was a generic image-load/CPU trace, and Microsoft's HDAudio provider is
inert on this machine anyway because `IntcAudioBus.sys` owns the link, not `HDAudBus.sys`.
`RTKVHD64.sys` ships **its own** manifest-based ETW provider that logs every codec verb.
See §10.

---

## 1. Identification, verified from silicon

Read directly off the chip rather than from any driver string or config file, and
cross-checked against the Windows registry on the same machine's own Windows install:

    nid 0x00 GET_PARAMETER 0x00  -> 0x10ec0295     vendor id, from the codec's parameter ROM
    nid 0x00 GET_PARAMETER 0x02  -> 0x100002       revision
    nid 0x01 GET_SUBSYSTEM_ID    -> 0x17aa2263     codec subsystem
    nid 0x12 GET_CONFIG_DEFAULT  -> 0x90a60130     internal / Mic In / "Other Digital"
    PCI config space offset 0x2c -> aa 17 44 22  = 17aa:2244
    Windows registry             -> INTELAUDIO\FUNC_01&VEN_10EC&DEV_0295&SUBSYS_17AA2263

Only one audio device is present; no USB audio; the only other codec on the link is the
Intel HDMI one. The vendor ID is returned by the chip and cannot be spoofed in software.

⚠️ Note the two different IDs. Kernel quirks (`SND_PCI_QUIRK`) match the **PCI SSID
`17aa:2244`**; hda patch-firmware `[codec]` lines match the **codec SSID `0x17aa2263`**.
Using the wrong one silently does nothing.

### The pin table

    0x12  0x90a60130  Fixed  Mic In    OTHER DIGITAL   <- the ONLY internal mic
    0x14  0x90170110  Fixed  Speaker   analog
    0x19  0x04a11040  Jack   Mic In    1/8"            <- headset mic, works
    0x1a  0x411111f0  None   (disabled)
    0x1b  0x90170150  Fixed  Speaker   analog
    0x21  0x04211020  Jack   HP Out    1/8"

There is **no analog internal mic pin** on this machine. Note the family also uses
`0x90a70130` (connection type 7 = Other *Analog*) on pins `0x1a`/`0x1b` for analog
internal mics — "internal mic" means two different things across this family, and ours is
the digital kind.

## 2. Topology, and what the generic parser does with it

The ALC295 has three input converters:

    ADC 0x07  <- Audio Selector 0x24  <- 0x12* 0x13 0x18      rates: 48000 ONLY
    ADC 0x08  <- Audio Mixer    0x23  <- 0x19 0x1a 0x1b 0x1d 0x12
    ADC 0x09  <- Audio Mixer    0x22  <- 0x19 0x1a 0x1b 0x1d 0x13   (fully muted)

Selector `0x24` already selects `0x12`, and ADC `0x07` supports a single fixed rate — the
signature of a PDM decimation path. So `0x12 -> 0x24 -> 0x07` is the dedicated
digital-microphone path.

Linux exposes exactly one capture PCM, on ADC `0x08`. The reason is in
`sound/hda/codecs/generic.c` — the parser filters out ADCs that cannot reach every active
input pin, and ADC `0x07` cannot reach pin `0x19`, the headset mic. So it keeps `0x08` and
drops `0x07`, and the digital pin gets read through the **analog** mixer.

This can be overridden with a pin-config patch that disables `0x19`, after which the
parser selects ADC `0x07` (confirmed: during capture `0x07 conv=0x10`, `0x08`/`0x09`
idle).

⚠️ **See correction C4.** This is a real mechanism but not the fault — working machines
drop ADC `0x07` in exactly the same way and read the DMIC through mixer `0x23`. On this
machine, forcing ADC `0x07` yields exact zeros, and so does the stock mixer path.

## 3. ⭐ The noise is a floating analog input — `COEF 0x08` bits 2+3

**This is the main result, and it survives every later correction.**

    COEF 0x08 = 0x6a8c   (Linux)   -> broadband noise, rms ~153, sustained
    COEF 0x08 = 0x6a00             -> EXACT digital silence

Measured on the normal capture path (ADC `0x08`, stock pin config). A 12-second capture
with the bits cleared contained **2 304 000 data bytes, not one of them non-zero**.

Bit map, two rounds, 3-second captures with 500 ms of head discarded, both rounds
agreeing:

    0x6a0c  (bits 2+3)      -> noise, sustained
    0x6a8c  (Linux)         -> noise, sustained
    0x6a00 0x6a80 0x6a08 0x6a04 0x6a84 0x6a88  -> exact silence

**Bits 2 and 3 must both be set for the analog input to pass.** Bit 7 is irrelevant to it.

### Two independent controls

**Electrical.** With the bits cleared (silence), enabling the codec's internal DAC→ADC
loopback and playing a 1 kHz tone gives rms 32621, peak 32768, dominant peak 1000.0 Hz.
⇒ the ADC, its DMA and the whole capture chain are **alive** with the bits cleared. Those
bits gate the analog *source*, not the converter.

**Acoustic.** A later two-point calibration with a headset in the analog mic jack:
at `0x6a8c` the capture contains **real speech** (burst/pause envelope, voiceband
300–3400 Hz tracking it at corr 0.88, pitch peaks at 155 Hz and 227 Hz, mains 50/100 Hz
10–13 dB *down*); at `0x6a00`, **exact silence**, rms 0.7, and speaking during the capture
changed nothing.

The acoustic control is the stronger one, and it was added specifically because the
electrical one has a blind spot: a loopback proves the converter and DMA work, but it does
**not** prove that a live external source would appear where we are looking. It now does
— for the shared path downstream of mixer `0x23`. It still does not prove that the DMIC's
digital leg *into* the mixer would appear.

### Why it matters

The "flat white noise" that defines this bug is an unconnected analog input being sampled.
It is not an undecimated PDM bitstream, not a badly-clocked microphone, and not mic data of
any kind. Any spectral argument about it — including the rise toward Nyquist, which looks
exactly like sigma-delta noise shaping — is analysing nothing.

⚠️ **See correction C1** for what this does *not* say about Windows.

## 4. ⭐ Method: init-time COEF writes reach state that live writes cannot

The finding in §3 was only reachable because the Windows register values were applied **at
codec init**, via hda patch firmware, instead of being written live to a running codec.

    [codec]
    0x10ec0295 0x17aa2263 0

    [verb]
    0x20 0x500 0x08        # SET_COEF_INDEX 0x08
    0x20 0x400 0x6a00      # SET_PROC_COEF

Loaded with `modprobe snd_hda_intel patch=<file>.fw`.

Anyone replaying vendor register state on an HDA codec should do it this way: a live write
test can return a false negative purely because the register is latched after init.

⚠️ Two caveats the initial release did not have. First, **see correction C2** — the
headline example of "took at init but was STUCK live" (`0x3a`, `0x40`) turned out not to
be configuration at all. Second, and worse, the harness assumption underneath it is false;
see §8, "A driver reload does not reset the codec".

Two registers, **`0x2b` and `0x67`, never take by any route** — live or at init, alone or
in combination. They read back `0x0` every time. They are not negative results; they are
untested, and whatever holds them off is not the live-write gate, because init-time writes
bypass it.

## 5. ⭐⭐ Reading the codec while Windows is recording

§10 of the initial release said the remaining unknown was "state the vendor driver holds
only while a capture stream is open, which no post-hoc dump can see". That measurement has
now been made, by bugchecking Windows in the middle of an active capture and booting Linux
with `snd_hda_intel.probe_only=3` so the codec driver never touches the codec.

**Only four registers move on Windows' teardown path:**

| COEF | Windows live (crashed mid-capture) | Windows after clean shutdown | Linux |
|------|------------------------------------|------------------------------|-------|
| 0x08 | **0x6a0c** | 0x6a00 | 0x6a8c |
| 0x3a | 0x10       | 0x3e   | **0x10** |
| 0x40 | 0x8800     | 0x88f0 | **0x8800** |
| 0x67 | **0x1200** | 0x1000 | 0x0 |

So the post-teardown oracle was ~85% right — 10 of 14 registers read the same live as
after teardown — but it was wrong about the one register the whole analysis rested on.

The live Linux-vs-Windows delta is these 12 registers:

    0x08=0x6a0c 0x0c=0x41ef 0x24=0x002d 0x26=0x0065 0x28=0x2200 0x29=0xa015
    0x2b=0x0181 0x44=0x4500 0x48=0xd811 0x49=0x0045 0x62=0x0077 0x67=0x1200

### 🚫 And the codec *tree* can never be read this way

`codec-after-linux`, `codec-after-windows` and `codec-after-crash` dumps are
**byte-identical** — same md5. Every converter reads `stream=0, channel=0` even though
Windows was actively streaming at the instant of the bugcheck.

The HDA **link reset** that `snd_hda_intel` performs at probe wipes widget state
(converters, pin controls, amps, GPIO) while leaving the vendor COEF bank intact — which
is exactly why the COEFs *did* differ and the tree did not. So "which ADC does Windows
use", "what does mixer `0x23` hold live", "which pins are powered" are **structurally
unanswerable** by any reboot-based oracle, no matter how the reboot is triggered. Do not
spend another crash on them.

## 6. Replaying the corrected values — negative

The 12 live values were applied at init, on the **stock ADC-`0x08`/mixer-`0x23` path**
(per C4, the configuration working machines actually use), against a baseline verified
exact-silent and a codec verified stock by cold boot:

* **the 11 non-`0x08` values, one per driver load** — 9 took at init; every one captured
  **exact zero**. (`0x2b`, `0x67` refused, as always.)
* **`0x08=0x6a0c` alone** — the entire live delta in the one register with acoustic ground
  truth. Produces sustained non-zero output that passes naive artefact filters, but a
  classifier validated against labelled recordings judges it **not audio**: stationary
  noise, modulation 1.04, dynamic range 1.3×, no speech envelope, energy rising to 33% in
  the 10–20 kHz band. It is the §3 floating input, nothing more.
* **all 12 applied together** — spectrally *identical* to `0x08` alone (rms 571 vs 591,
  same rising-HF shape, same verdict). The other eleven registers contribute nothing.

⇒ The complete Windows live vendor-COEF state, replayed faithfully at init on the path a
working machine uses, does not turn the microphone on. **Static nid-`0x20` state is
excluded on both oracles.** (Scope: nid `0x20` only — see C3.)

## 7. What Windows does — the whole stack, taken apart

Windows records this microphone correctly, so it is a working reference implementation.
Every layer was examined for a per-machine configuration, and **there is none**:

| source | result |
|---|---|
| `RTKVHD64.sys` pin-config tables | all gated on Realtek **reference-board** SSIDs (`10EC10AE`, `10EC108C`, …) via `SET_SUBSYSTEM_ID`. Never matches `17AA2263`. |
| `RTKVHD64.sys` vendor COEF inits | one sequence, repeated; contains `0x2d=0x3020`, which **bricks this codec**. Not for the ALC295. |
| `RTKVHD64.sys` constants | none of our measured COEF values appear as constants anywhere in the binary ⇒ they are runtime state, not settings |
| `RTAIODAT.DAT` 2018, 19 MB (installed) | `MDTR` format, 1420 platform records. **No `17aa2244`, no `17aa2263`.** |
| `RTAIODAT.DAT` 2020, 39 MB | 1794 records. **Same — absent.** |
| the installed INF | endpoint naming and effects only |
| the OEM extension INF | matches our SSID **exactly** — and installs audio effects only |
| `NHLT` ACPI table | **EndpointCount = 0**, payload `deadbeef` — the same empty table Windows reads |
| a 76 MB ETW audio trace | image-load / CPU trace; zero HDA verb traffic — but see **C5** |

Windows drives this microphone with **generic runtime behaviour**, not a vendor blob.
There is no magic init sequence to lift out of the driver — which is precisely why a
*runtime* verb log is the right next instrument, and a static one never was.

Architecturally, Windows runs the codec under **Intel Smart Sound** (`IntcAudioBus`
running, `HDAudBus` stopped, service `IntcAzAudAddService`, `ForceSST=1`), with
`RTKVHD64.sys` as the miniport. Its per-platform registry key is keyed by the PCI SSID
`17aa2244` and holds runtime state (`Pin12=1`, `ChannelConfig=3`, 48 kHz), not
configuration.

## 8. Traps worth knowing on this codec

Every one of these produced a wrong result here before it was understood.

* 🚨 **A driver reload does NOT reset vendor COEFs. Only a power cycle does.**
  `modprobe -r snd_hda_intel; modprobe snd_hda_intel` restores only the registers the
  driver itself writes; everything else keeps whatever the last test left. Some registers
  **latch** — they accept a new value and then refuse to go back, across reloads, six
  consecutive loads of a firmware setting `0x3a=0x0010` all read back `0x3e`.
  ⇒ Any multi-phase sweep that "reloads between phases to restore the baseline" has been
  running against a silently drifting reference. A `TOOK` verdict can be a *persisted
  earlier write*; a `STUCK` verdict is only valid relative to whatever the register
  happened to hold at that moment. **Snapshot before, verify restore after, and
  power-cycle for a true baseline.**
* ⚠️ **Ten registers out of 1024 move on their own.** Established by diffing Linux-only
  dumps against each other, no Windows involved: `0x20 0x35` bit 15 and `0x53 0x01` track
  headphone-jack presence and revert exactly; `0x20 0x46` bit 9 and seven `0x58`
  registers (the headphone-amp calibration bank written by `alc285_hp_init`) latch on jack
  insertion and **do not revert on removal**. They are stable across repeated reads, so
  they are not jittering telemetry you would notice — they are event-latched analog
  measurements, indistinguishable from deliberate configuration in a static diff.
  **Check any cross-OS delta against a same-OS control before calling it evidence.**
* 🚨 **Two registers brick the codec.** `COEF 0x2d = 0x3020` and clearing `COEF 0x33`
  bit 15 both stop it answering; no module reload recovers either, only a full power
  cycle. Never replay a vendor COEF sequence wholesale — write one register at a time and
  verify the codec still answers after each.
* **Mute every output pin before believing any microphone result.** Frequency tracking
  does not distinguish an electrical loopback from an acoustic path. This cost two
  retracted results (§9).
* **The first capture after a driver reload is a full-scale DC rail.** On the stock path,
  the first stream open after `modprobe` pins the input at +32767 for ~1.1 s, then decays
  exponentially to exactly zero — 0.0% energy in every band from 50 Hz to 20 kHz, DC
  offset ~+10950. It is the analog front end powering up, not a signal, and it fooled an
  artefact filter into rejecting a whole test run. It is triggered by the **first stream
  open after a reload**, and the decay starts *at open*, so waiting does not help: open
  the stream once, throw the result away, and measure on the second open.
* **"Not zero" is not a signal.** Apparent hits in a bit sweep were all converter
  artefacts: a stuck DC alternating at Nyquist, a full-scale stuck value, decaying
  transients. Require: sustained across the window, channels not bit-identical, not a
  fixed alternation at Nyquist, many distinct values.
* **Validate your verdict function against labelled ground truth.** The classifier used
  for most of this work scored **5 of 8** on a labelled reference set — it called a
  deliberate room-tone control "speech", and missed real speech because a low male
  fundamental puts most energy below 300 Hz and an uncorrected DC offset put 0 Hz at the
  top of the spectrum. Corrected to 8/8, the entire archived corpus was re-judged; no
  negative became a hit, but that was luck, not method.
* **Live values differ from `probe_only=3` dumps.** `COEF 0x10` reads `0x0120` live and
  `0x0320` with the driver's init suppressed. Do not plan bit tests off a probe-only dump.
* `modprobe -r snd_hda_intel` fails while PipeWire holds the card; it must be **masked**,
  not merely stopped, because socket activation restarts it instantly.

## 9. Retracted results, and why they survived review

Kept deliberately — both are instructive, and both are shipped in `retracted/`.

**`COEF 0x07` bit 10 "DMIC clock enable".** It is an internal DAC→ADC loopback. Tone tests
recovered 1 kHz at over a million times the median bin and tracked frequency across two
test tones — and all of it was the machine recording its own playback. An earlier
candidate had already failed the same way through speaker bleed. **Two independent traps,
each producing a clean frequency match.**

**"The DMIC clock theory is dead."** Concluded from COEF dumps taken after a warm reboot
from Windows — i.e. after the vendor driver ran its shutdown path. Any register the driver
clears on the way out reads identical to never-set. The measurement could not have
detected a stream-scoped enable, so it never established what it was cited for. §5 is the
experiment that finally could, and correction C1 is the claim it overturned.

## 10. What is left

**Scope first.** "The static configuration space is exhausted" is now three separate,
narrower statements: nid-`0x20` COEF state is excluded on both capture paths (§6); seven
other vendor register banks have never been swept (C3); and no static Windows artefact
holds per-platform configuration (§7).

Linux's own init is almost a no-op in this space — across 8 banks × 128 registers, its
entire delta from the uninitialised power-on state is **two registers** (`0x20 0x10` and
`0x20 0x36`). The seven unexplored banks are byte-identical initialised vs uninitialised,
which makes them an unusually clean diff surface.

**The next instrument is a runtime verb log, not another dump.** `RTKVHD64.sys` registers
a manifest-based ETW provider at `DriverEntry` — unconditionally, so no registry knob is
needed:

    {3c9fef08-fa30-4c6f-b9b6-b8329e816d5b}

Its `etwVerb`/`opSendVerb` event carries `VerbCommand`, `VerbCount`, `Command`,
`Response`, `Index`, `Data` and `pin` — `Index`+`Data` being the COEF index/data pair, and
`Command`+`Response` meaning **reads are captured too**. `etwStreamOperation` carries
capture start/stop with `SampleRate`, `Channels`, `ChannelMask` and `FormatTag`.

That yields the **timestamped sequence of verbs Windows sends, correlated to capture
start**, from a normal running system — no bugcheck, no test-signing, no driver injection.
It answers the one question no static diff ever could: not *what values* Windows holds,
which we now have in full and which do nothing, but *in what order and at what moment* it
writes them. Given §7 — that Windows drives this microphone with generic runtime
behaviour rather than a blob — a sequence, a timing dependency, or a verb that is not a
COEF write at all is the remaining shape the answer can take.

Still open behind that: why `0x2b` and `0x67` refuse writes by any route, and the seven
unswept vendor banks.

---

## 11. ⭐⭐⭐ 2026-08-21 — the microphone works, on a Windows warm reboot

This section supersedes the framing of everything above it. The internal microphone is
not merely alive; it records real, faithful audio under Linux on a stock kernel. It just
cannot be switched on from Linux.

### 11.1 The observation that cracked it

Not a register value — a **timeline**. Reading `journalctl --list-boots` against the
archived codec dumps showed that every dump holding the "rich" register state sat in a
Linux boot that followed a **Windows session with no power loss**, and every dump holding
stock values followed a **power cycle**. No exceptions across two days of samples.

Both halves are necessary:

- Windows state alone is not enough. A boot straight off Windows with the codec driver
  suppressed (`snd_hda_intel.probe_only=3`) reads stock values — the state is there, but
  nothing has built the capture path.
- Linux init alone is not enough. Every cold boot is dead.

**Windows' residual state + Linux's own init on top of it = a working microphone.**

### 11.2 Confirmation

Predicted, then tested: boot Windows to the desktop, warm-reboot into Linux, read the
codec. The state reproduced on the first attempt.

    reg          warm-from-Windows   previously-observed working   stock/dead
    0x20 0x2b    0x181               0x181                         0x0
    0x20 0x3a    0x38                0x3e                          0x10
    0x20 0x40    0x88f0              0x88f0                        0x8800
    0x20 0x0c    0x41ef              0x41ef                        0x1ef
    0x5c 0x0f    0x0                 0x0                           0x1

Then the audio, with output pins muted throughout — the loopback trap of §9 is excluded
by construction, and every figure below is paired against a control:

    point (boost/capture)   dead+speaking   warm+silence   warm+music   warm+speech
    linux-default  3/63     630             2595           24278        23574  (clips 41%)
    windows-values 0/52     7.6             28.9           550.6        735.2
    boost0-maxcap  0/63     19.7            70.1           1500.5       1858.9

`analyse-wav.py` returned **✅ real speech** at all three gain points. The clean witness is
`boost0-maxcap`: no clipping, dc −0.3, frame RMS swinging 36..3232, `mod` 89, dynamic
range 98×, voice-band share 52 %.

Structural confirmation on the same music, same room, only the codec state differing:

    capture                      beat autocorrelation   spectral flatness
    music, dead/stock codec      0.067  (no beat)       0.97  (pure noise)
    silence, warm-Windows        0.075  (no beat)       0.63
    music, warm-Windows          0.607  (strong beat)   0.29  (tonal)

Tempo 119.7 BPM, with the 59.8 half-time also present.

**The decisive test was third-party.** 25 s of room audio through the internal microphone,
percentile-normalised, submitted to a commercial acoustic-fingerprinting service: it
returned the correct title, artist, album and year. Fingerprint matching depends on precise
spectral peak positions and their timing offsets. Noise cannot match; a microphone with a
badly wrong response cannot match either. This is the strongest available evidence that
the DMIC *reproduces* sound rather than merely responding to it.

### 11.3 The reverse bisect — static register state is excluded

A live working codec permits the experiment nobody could run before: push **working →
dead** and watch for a collapse, rather than pushing dead → working against registers that
refuse to be written.

Candidate set: every register differing between the working dump and **two independent
dead dumps that agree with each other** — 2400 registers across 15 vendor nodes. Requiring
the two dead samples to agree filters per-boot noise, and the filter validated itself by
correctly discarding `0x20 0x10` and `0x20 0x36`, both previously reclassified as noise.
That left 17 candidates: 13 on nid `0x20`, three on `0x58`, one on `0x5c`.

**Thirteen of them were forced to their dead values simultaneously. The microphone kept
working** — 1568 vs 2008 rms on a paired A/B, roughly 22× over the dead floor either way.
That set includes `COEF 0x08`'s analog gate, `0x0c` bit 14, `0x3a` and `0x40`.

The other four were eliminated individually:

- `0x5c 0x0f` — forced to its dead `0x1`: 640 vs 725 restored. Negative. This had been the
  last single-register candidate standing.
- `0x20 0x2b` — **read-only**. Written with an arbitrary `0x5555` on the working codec, it
  held `0x181` exactly. It refuses `0x181` on a dead codec and `0x0` here. Refusing in
  both directions against an arbitrary value is a status register, not a control. The
  "Windows fingerprint" register is an *effect*.
- `0x58 0x09 / 0x18 / 0x1b` — Windows sends **zero verbs to nid `0x58`** in a full
  3745-verb boot trace. Hardware amp calibration, re-run at power-on. They also do not
  refuse writes, they *mask* them (`0x5555` → `0x4058` / `0x4040` / `0x1555`), and the
  microphone kept working while they were perturbed.

**And the codec tree is identical.** §5 concluded no tree question was answerable, because
the link reset wipes the tree before any dump can be taken — true for post-teardown
sampling, but a *live working codec* sidesteps it. `/proc/asound/card0/codec#0` live-working
versus cold-boot-dead differs by **five lines in 287**, every one of them caused by the
test's own mixer settings (the boost set to 0, the output mute, capture at 63).

No observable static state — vendor registers or codec tree — distinguishes a working
microphone from a dead one on this machine.

### 11.4 What the ETW verb trace can and cannot answer

In 3745 decoded verbs from a Windows boot: `SET_PROC_COEF` (verb `0x400`) and
`GET_PROC_COEF` (`0xC00`) appear **zero times**, against **1657** `SET_COEF_INDEX`. The
provider logs the index verb and drops the data verb. **COEF values are unrecoverable by
this route** — do not re-mine the trace for them.

The index histogram is still informative. Repeated selects of a few indices with no data
verb between them is the signature of a **poll loop**: `0x29` 761 times, `0x26` 379 times,
`0x2b` 107 times — and `0x2b` is now known to be read-only status. Windows appears to be
waiting on something. Note also the scale: 1657 index selects during Windows boot against
**two** COEF registers written by Linux init in total.

### 11.5 The hypothesis

That Windows starts a **clock or power domain** — plausibly the PDM/PLL supply for the
digital microphone — which survives a warm reboot and stops on power loss.

It is the only explanation so far consistent with all of: no static replay works; the
correlating registers are read-only status; the codec tree is unchanged; Windows state
alone is insufficient; Linux init alone is insufficient; and Windows polls a status
register 107 times at boot.

The discriminating experiment is **S3 suspend/resume on the live working state** — run
the same night; see §11.8. The microphone **survived**, while every vendor register
reverted to stock. So the state survives a full codec re-initialisation and dies only on
power loss, and no host-readable register tracks it.

### 11.6 ⚠️ Two method traps caught by controls

Both would have been published as findings if the control had not been run.

**A key/chroma estimate is confounded by microphone response.** Krumhansl-Schmuckler key
detection on the music capture returned "F# major", fit 0.845 — and returned F# major on
**pure silence** (0.69) and on **dead-codec noise** (0.73). It was reading the microphone's
own frequency colouring. Tempo autocorrelation, by contrast, separated cleanly (0.607 vs
0.067). Report the tempo; discard the key.

**Acoustic fingerprinting produces confident false matches on thin material.** The first
submission — an un-normalised capture peaking at ~26 % of full scale — returned a
specific, plausible, *wrong* track with full album and label metadata. The same audio,
percentile-normalised, returned the correct one. Normalise before submitting, ignore
transient clicks when computing the gain, and never treat a single identification as proof
without a recognisable control.

### 11.7 Practical note

Until there is a native fix: boot Windows to the desktop, warm-reboot into Linux, and the
microphone works for the rest of that Linux session. Use `Internal Mic Boost` **0** — the
Linux default of 3 applies roughly +30 dB to this pin and clips about 40 % of samples into
a DC rail, which is itself a measurement trap (§8).

### 11.8 ⭐⭐⭐ The S3 test — the capability survives, the register state does not

Run the same night, on the live working state. The discriminating experiment of §11.5,
and the result is unambiguous.

A real `deep` suspend, 12 seconds (`PM: suspend entry (deep)` → `PM: suspend exit`):

    register        pre-suspend   post-resume      cold-boot/dead
    0x20 0x08       0x6a00        0x6a8c           0x6a8c
    0x20 0x0c       0x41ef        0x1ef            0x1ef
    0x20 0x2b       0x181         0x0              0x0
    0x20 0x3a       0x38          0x10             0x10
    0x5c 0x0f       0x0           0x1              0x1

**Every register reverted to its stock value. The microphone kept working.**

    measurement                        pre-suspend   post-resume
    rms at boost0-maxcap, music         1099          1390
    rms, music paused                   —             241     (5.8x ratio)
    third-party song identification     —             ✅ correct track

The residual 241 with music off is not a noise floor: `mod` 15.3 with frame RMS swinging
59..893 is room events — fan, movement — not stationary hiss.

**This is the strongest exclusion in the whole record.** A cold boot has stock registers
and a dead microphone. A post-resume boot has stock registers and a working microphone.
The registers therefore cannot be what distinguishes the two states — they are symptoms
of the state, not the state itself. That is a third independent proof, arrived at without
writing anything: §11.3 forced them to dead values and the mic survived; §11.3 also showed
`0x2b` is read-only; and now a suspend/resume resets all of them with no effect on
capture.

⚠️ **Consequence for anyone testing this: there is no register you can read to predict
whether the microphone will work.** An earlier version of this document proposed `0x2b`
as an indicator. That was wrong and is retracted here — the only reliable test is to
record something.

**What it implies about the mechanism.** S3 on this machine drops power to the codec and
the driver re-initialises it on resume, which is what resets the coefficients. Whatever
Windows leaves behind therefore survives a full codec re-initialisation, and dies only on
a real power cycle. That is consistent with a clock or power domain that keeps running
across suspend but stops when the rail actually drops — and it is *not* consistent with
any state the host can read back.

**Practically:** one Windows warm boot holds for the whole Linux session, across folding
the folio shut. Suspend/resume does not cost you the microphone.

### 11.9 ⭐⭐⭐ The state survives every reset software can issue

§11.8 showed the microphone surviving an S3 suspend. The obvious follow-up is how far down
that goes. It goes all the way.

Each step below was verified by **third-party acoustic fingerprint identification** of
whatever was playing in the room, not by signal level — four different tracks across the
evening, every identification correct.

    action                                    registers after   microphone
    13 candidate registers forced to DEAD     as written        works
    0x40 left permanently at dead 0x8800      dead              works
    S3 suspend/resume (deep, 12 s)            reset to default  works
    codec AFG D3 -> D0                        reset to default  works
    FUNCTION_RESET (nid 0x01, verb 0x7ff)     reset to default  works
    PCI remove + rescan, full driver re-probe reset to default  works
    removing machine power                    reset             DEAD

Every one of those resets the vendor coefficients — `0x20 0x08` `0x6a00`→`0x6a8c`, `0x2b`
`0x181`→`0x0`, `0x5c 0x0f` `0x0`→`0x1`. The microphone is indifferent to all of it.

**The codec's own power-down state (D3) does not clear it. Its hardest software reset
(`FUNCTION_RESET`) does not clear it. Tearing the PCI device out and re-probing the driver
from zero does not clear it.** Only removing power from the machine does.

### 11.10 Zero registers separate working from dead

The complete comparison, made possible by having a working codec whose registers had been
reset: a full 160-register × 15-node dump of the **working** post-S3 codec against the two
**dead** cold-boot dumps — 2400 registers.

    WORKING (post-S3)  vs  DEAD (post-powercycle)   15 differ  (5 non-volatile)
    WORKING (post-S3)  vs  DEAD (cold boot)         10 differ  (3 non-volatile)
    WORKING (post-S3)  vs  WORKING (pre-suspend)    28 differ  (21 non-volatile)

**The two working states differ from each other more than either differs from a dead
codec.** Exactly one register differed from both dead dumps — `0x5a 0x01`, `0xf` vs
`0x10f` — and it survived about a minute: it reads `0x10f` in the two *earlier* working
dumps as well, making it a post-S3 artefact rather than a marker.

*Method note: that candidate was briefly treated as a lead before all four dumps were
checked. With three-plus samples per state available, check every one before calling a
single-register difference a finding.*

### 11.11 What is actually left

The enabling state is not codec register state, not the codec tree, and not reachable by
any reset software can issue. It survives the codec's own power-down and a complete driver
re-probe, and clears only on a true power-on reset. That is the signature of **a clock or
power rail that Windows starts and that nothing short of power loss stops.**

Two candidate surfaces were closed the same night:

- **The SoC's own digital-microphone pins are unused.** Pads 89–92 (`DMIC_CLK_0/1`,
  `DMIC_DATA_0/1`) sit in GPIO mode with **both buffers disabled** (`0x300` = RXDIS+RXDIS)
  *while the microphone is working*.
- **The `NHLT` ACPI table is 45 bytes** — essentially empty, describing no DMIC endpoints.

So the PDM microphone is on the codec, not on the SoC, and the Intel SST/AVS path was never
the answer — consistent with that fix having tested negative earlier.

**The one untested surface** is the rest of the platform: pad configuration registers for
all 152 pins, GPIO line state, PCI configuration space, clock tree, ACPI device power
states. A complete capture was taken while the microphone was working; the comparison
requires the same capture on a dead boot, which needs a power cycle to produce.

## 12. ⭐⭐⭐ 2026-08-21, later — the cold boot, and the end of the readable surfaces

§11.11 closed by naming one untested surface and the experiment that would settle it: the
same platform-wide capture, taken on a dead boot. That experiment has now been run.

### 12.1 The cold boot is dead, and the boundary is exactly power

The machine was powered off — a real `systemd-poweroff`, confirmed in the journal, not a
reboot — and powered back on into Linux. The platform capture was taken **first**, at one
minute of uptime, before anything else touched the machine. Then the acoustic oracle of
§11.2 was run against music playing in the room.

    capture                        rms      p99.9     third-party ID
    working (post FUNCTION_RESET)  3177     32768     correct
    working (post codec D3)        2856     32767     correct
    working (first music capture)  1606      6033     correct
    cold boot, music playing       25.4       252     NO MATCH

The measured dead floor is 20–70. The result is not a weak signal, it is no signal: the
normaliser's 60× gain ceiling was reached and the loudest 0.1 % of samples still sat at
252 counts. The prediction held.

Combined with the earlier tests, the boundary is now drawn precisely:

    cold boot, Linux only                          dead
    warm boot from Windows                         works
    warm reboot Linux -> Linux from a working state works
    S3 suspend/resume                              works
    codec D3 power-down                            works
    codec FUNCTION_RESET                           works
    full PCI remove + rescan                       works

**Nothing software can do removes the state. Removing power always does.** For a user,
that reduces to a workaround worth stating plainly: **one Windows boot per power cycle,
not per reboot.** Reboots, suspends and driver reloads are all free once the state exists.

### 12.2 The platform capture explains nothing

`platform-state-warm-working` versus `platform-state-cold-dead`, sixteen files.

**Byte-identical:** all 152 pinctrl pads (`pins`, `pinconf`, `pinmux`, `gpio-ranges`), the
HDA controller's PCI configuration space at both 256- and 4096-byte depth, the iGPU
extended configuration space, the ACPI table list, every ACPI device's `_STA`, and the
controller's runtime power status.

**Different, and all of it accounted for:**

- `clk_summary` and `gpio-all` — `tps68470-clk` at 24 MHz bound to `i2c-INT3477:00 xvclk`
  versus 19.2 MHz unbound, and the `s_enable` / `s_resetn` GPIO lines claimed versus
  unclaimed. That is the **camera** PMIC on this tablet's other unsupported device; the
  working boot had had the camera lane exercised. Nothing to do with audio.
- `lspci` — twenty lines of IRQ numbers, MSI addresses, `LaneErrStat` and PCIe
  de-emphasis level. Boot-to-boot allocation and link-training variation.
- `codec-tree` — three lines, all of them **our own mixer settings**: node `0x12` Amp-In
  `0x03` (the driver's default microphone boost) against the `0x00` this work sets, and
  nodes `0x14` and `0x1b` Amp-Out `0x80`, the output mutes applied per §9. Routing,
  connection lists and pin configuration are identical.
- `power.txt` — `runtime_suspended_time`, a counter.

No pad, no PCI register, no ACPI object, no clock and no codec node separates working from
dead. Taken with §11.3 — 2400 codec registers, zero of which separate the states — and the
byte-identical codec tree, **every surface this work could read has now come back empty.**

A calibration point on how little that leaves: two *working* captures differ from each
other by five pinctrl RX-level bits on unrelated pads. Working and dead differ by less
than working and working.

### 12.3 The last unread surface: the controller's MMIO block

> ⚠️ **Superseded — read §13.1 before this section.** The `LCTL` / `SCF` link-clock
> hypothesis developed below was tested on 2026-08-22 and is **negative**. The full 16 KiB
> BAR0 is byte-identical between a working boot and a dead one. The section is kept intact
> because the method is reusable and because a reader deserves to see which way the
> evidence actually pointed before it was tested.

One gap remained, and it is worth naming precisely because it had been quietly assumed
away: `lspci -xxxx` dumps PCI **configuration** space. It does not touch the controller's
**memory-mapped** register block, which is where the HD-audio controller actually lives.
That had never been read.

It has now been read on the dead side. Method, since the traps are the useful part:

- Map `/sys/bus/pci/devices/0000:00:1f.3/resource0`. Do **not** use `/dev/mem` on this
  platform; it hard-hangs the machine.
- The controller **runtime-suspends when idle**, and MMIO reads against a device in D3
  return all-ones. Force `power/control=on`, wait for `active`, dump, restore. A dump
  taken without this is sixteen kilobytes of `0xff` that looks like data.
- Take **two back-to-back passes**. Whatever differs between them is free-running and must
  be masked before any working-versus-dead comparison. Here that is seven offsets: the
  wall clock at `0x0030`, the CORB and RIRB ring pointers at `0x0048` and `0x0058`, the two
  per-link frame counters, and two aliases at `0x2030` and `0x3030`.
- BAR4, 64 KiB, is the Intel cAVS **DSP aperture**. It was deliberately left untouched:
  reading it while the DSP power domain is gated can hang the machine, and the Processing
  Pipe capability header shows the pipe idle, so the domain is probably gated.

The block is not empty. It carries a five-entry Intel extended-capability chain:

    @0x0c00  ID 2  Multi-Link                  -> @0x0800  ID 3  Processing Pipe (DSP)
    -> @0x0500  ID 1  Global Time Sync         -> @0x1f00  ID 5  DMA Resume
    -> @0x0700  ID 4  Software Position Based FIFO -> end

Offsets and bit fields verified against `include/sound/hda_register.h` in the running
kernel's own source, not from memory: `AZX_ML_BASE` 0x40, `AZX_ML_INTERVAL` 0x40,
`SCF` = bits 3:0, `SPA` = bit 16, `CPA` = bit 23.

The **Multi-Link** block is the interesting one. Link 0 is the external HD-audio link that
carries the ALC295; link 1 is display audio.

    reg                  link 0 (DEAD)                       link 1
    LCAP   +0x00         0x00000007  (legacy HDA, not ALT)   0x0000001f
    LCTL   +0x04         0x00810002  SCF=2 SPA=1 CPA=1       0x00810004  SCF=4
    LOSIDV +0x08         0x0000fffe                          0x0000fffe
    LSDIID +0x0c         0x00000003                          0x00000004
    LPSOO/LPSIO +0x10    0x00020000                          0x00020002
    LOUTPAY +0x20        0x001c000d                          0x000b0003
    LINPAY  +0x30        0x000d0005                          0x00000000

`LCTL.SCF` is the link clock-frequency select; `SPA` and `CPA` are the link's requested and
actual power state. This is the first candidate in the entire investigation that fits the
shape of the answer rather than contradicting it. It is **in the PCH, not in the codec**,
which is what a state surviving codec resets and dying on power removal requires. And
unlike every vendor COEF this work chased for two days, **these registers are writable.**

That is a hypothesis with an address, not a result. The dead-side dump exists; the
working-side dump requires another Windows warm boot, and the comparison — masked by the
volatility list — is the next experiment. It may well come back empty like the others.

### 12.4 Status

The root-cause question is open. The user-facing question is answered: the internal
microphone on this machine can be made to work under Linux, on a stock kernel, by booting
Windows once per power cycle. Everything else — reboots, suspend, driver reloads — is free.

What this section adds to the record is mostly negative, and deliberately so. Six candidate
surfaces were closed: the pad configuration of every pin on the SoC, PCI configuration
space, the ACPI device tree, the clock tree, the codec's own topology, and 2400 vendor
registers. A reader arriving at this problem should not spend time on any of them.

---

## 13. ⭐⭐⭐ 2026-08-22 — the readable surfaces are now genuinely exhausted

Section 12 ended with one hypothesis holding an address: the controller's memory-mapped
register block, and specifically the HD-audio Multi-Link `LCTL.SCF` link-clock select.
This section tests it, tests four more things, and closes all of them.

Everything below was measured on a machine where the working state can be switched on
demand — boot Windows, warm-reboot into Linux — so each result is a one-variable
comparison against a control taken on the same boot, not a comparison between two
different days.

**Method note, and it matters.** Every negative here is paired with a **positive control**
on the same or an adjacent boot: a commercial acoustic-fingerprinting service identifying a
real track through the internal microphone. Without that, a negative result is
indistinguishable from an oracle that quietly broke — which nearly happened once (§13.2).
Captures are scored raw and 100 Hz high-passed; the dead side has essentially no noise
floor, so the high-passed RMS is the discriminator. Dead floor is **HP100 ≈ 17**.

### 13.1 🔴 BAR0 is excluded — and `GPROCEN` is not the mechanism

The working-side dump that §12.3 was waiting for was taken on a warm-from-Windows boot on
2026-08-22 at 08:10. Positive control on that boot: correct track identified from 25 s of
room audio. Then the full 16 KiB BAR0 was dumped and diffed against the cold-dead dump.

    differing offsets, after masking the 7 known volatiles
    (0x30 0x48 0x58 0xc58 0xc98 0x2030 0x3030):     0 of 4096

Zero. A **working** controller and a **dead** one are byte-identical across their entire
memory-mapped register block.

Two specific things die with it:

* **`LCTL` link 0 = `0x00810002`** on the working boot, the dead boot, and — from the
  Windows-side dump — under Windows too. `SCF` is 2 everywhere, in every state, under both
  operating systems. 🔴 The link-clock hypothesis of §12.3 is **negative**.
* **`PPCTL @0x0804` = `0x00000000` on the working Linux boot.** Windows idles at
  `0xc00003c1` — `PIE` plus `GPROCEN`, the DSP processing-pipe enable. So Linux captures
  real audio from the internal microphone **with the processing pipe globally disabled**.
  `GPROCEN` is how Windows routes its audio; it is not what makes the microphone work.
  🔴 Negative as a fix.

Every Windows-vs-Linux delta in the controller registers — `WAKEEN`, `LOSIDV`, the iDisp
link power bits — is Linux-identical between warm-working and cold-dead, so it is
cross-driver noise rather than the mechanism.

### 13.2 🔴 Is the Windows stack even necessary? Tests A2 and A1

Before spending more effort reverse-engineering the Windows driver, two experiments bounded
what part of Windows is doing this. Both work by disabling a layer **in Windows**, doing a
full power off, cold-booting Windows, verifying the layer really is absent, then warm
rebooting into Linux and recording.

**A2 — disable the PCI audio controller.** No kernel driver issues a single verb to the
codec that boot; the DSP is never brought up.

**A1 — disable only the Realtek codec function driver** (`INTELAUDIO\FUNC_01&VEN_10EC&
DEV_0295&…`), leaving the controller and the DSP bring-up intact and running.

| capture | raw RMS | **HP100 RMS** | distinct | identified |
|---|---|---|---|---|
| cold-dead-2 room tone | 17.9 | 16.21 | 165 | — |
| A1 room tone (same boot, silent) | 28.0 | **17.04** | 553 | — |
| **A1 + music** | 31.6 | **16.97** | 544 | **no** |
| **A2 + music** | 89.0 | **18.11** | 1638 | **no** |
| working boot + music | 2904.6 | **1299.82** | 30021 | **yes** |

Both negative. Playing music moved the A1 capture by **−0.07 RMS** against that boot's own
silent floor, and no match came back even at 510× gain.

* ✅ **A2 excludes firmware, BIOS and the ME** arming the microphone on their own. Something
  in the Windows audio stack is a genuine prerequisite.
* ✅ **A1 shows `RTKVHD64.sys` is necessary** — remove only the codec function driver and the
  arming dies, though everything upstream came up normally.
* 🔴 **A1 also shows the DSP alone is not sufficient.** A1 is exactly the condition where the
  DSP core is powered and running and nothing else happens, and the microphone stayed dead.

⚠️ **Two negatives in a row is when an oracle should be distrusted.** A1 and A2 cost three
power cycles, a debug-boot flag change and two disable/restore cycles between them and the
last confirmed positive. A positive control was therefore run before either negative was
allowed to count: restore everything, full power off, normal cold Windows boot, warm reboot,
record. It came back a **match**. Both negatives stand.

### 13.3 🔴 The codec verb interface, tried as a *sequence* — negative

Earlier sections excluded static vendor-register state. They did not exclude the
possibility that the *order* of Windows' writes matters — that the codec is a state machine
and the values are only the residue of the walk.

A full CORB ring capture from Windows gave 256 entries with their payloads. `replay-corb.py`
replays all of them in true chronological ring order (write pointer `0x91`, so 146..255 then
0..145), decoded with the kernel's own command-packing rule, with the `GET_PROC_COEF`
read-backs left in place and interleaved with the pin, amp, power and stream verbs that
bracket them. The burst is 53 `SET_AMP_GAIN_MUTE`, 42 `SET_COEF_INDEX`, 28 `SET_PROC_COEF`,
14 `GET_PROC_COEF`, 9 `GET_PIN_SENSE` and the rest.

| capture | raw RMS | HP100 RMS | identified |
|---|---|---|---|
| same-boot silent floor | 28.0 | 17.04 | — |
| **ordered replay + music** | 21.3 | **17.30** | **no** |

**The validity control is what makes this load-bearing.** The replayed state was read back
*after* the recording and was still live and still exactly the Windows values —
`0x03=0x0002 0x05=0x0700 0x08=0x6a0c 0x0c=0x41ef 0x10=0x0220 0x11=0x0000`, and `nid 0x5c
0x0f=0x0000`. The codec really was in the Windows post-restart state, reached in the Windows
order, and it captured nothing.

🔴 **The codec verb interface is now excluded as state and as sequence.** Note in passing
that `0x0c = 0x41ef` — bit 14, the long-standing standout — does latch, and changes nothing
on its own.

### 13.4 ⭐⭐⭐ What Windows actually does: the DSP IPC trace, decoded

Since the codec's verbs are not the mechanism but its driver is required, the remaining
Windows-side channel is DSP IPC, which never appears in the CORB ring. A trace of one
capture-open was captured on Windows and decoded field-by-field against the kernel's own
`sound/soc/intel/avs/messages.h`:

    LOAD_LIBRARY lib_id=1..4, dma_id=31            (~4.9 ms each, at capture-open)
    CREATE_PIPELINE ppl=4 prio=0 / ppl=5 prio=1
    ppl 4: copier(mod 3,inst 0) GATEWAY node_id=0x906 [HDA_LINK_INPUT vindex=6] buf=384
        -> peakvol(mod 4,inst 0) 2ch target_volume=0x7fffffff (unity, no curve)
        -> copier(mod 3,inst 1) no gateway
    ppl 5: copier(mod 3,inst 2) GATEWAY node_id=0x101 [HDA_HOST_INPUT vindex=1] buf=1920
    BIND 3:0->4:0, 4:0->3:1, 3:1->3:2
    SET_PIPELINE_STATE PAUSED -> RUNNING -> (12.3 s capture) -> PAUSED -> RESET

#### 🚨 The gateway is `HDA_LINK_INPUT`, not `DMIC_LINK_INPUT`

`dma_type` 9, not 11. **Windows does not use the PCH's dedicated PDM/DMIC interface at
all.** The microphone audio arrives at the DSP over the HD-audio link from the ALC295 —
exactly the source Linux's own legacy path already uses.

This is the single most useful positive fact in the whole section:

* It **kills the "the PDM interface is unarmed" family of hypotheses**, which is where the
  investigation had been pointing for two days.
* It **independently explains A1**: the codec must be streaming onto the link, so the codec
  function driver is necessarily required — which is what A1 measured.
* It means the difference between working and dead is *not* a different data path. Both
  operating systems pull the microphone through the codec and over the link. Linux even
  does it with the DSP pipe disabled entirely (§13.1).

Decoder and full decoded trace ship in [tools/decode-sst-ipc.py](tools/decode-sst-ipc.py)
and [evidence/sst-ipc-decoded.txt](evidence/sst-ipc-decoded.txt).

### 13.5 🔴 DSP-resident state is excluded

The four `LOAD_LIBRARY` calls run at capture-open and are **never undone** — the pipelines
are deleted at the end of the trace, the libraries are not. Since Linux's `snd_hda_intel`
never touches the DSP aperture, anything left in DSP memory would survive a warm reboot and
be wiped by a power cycle. That is exactly the observed shape, so it was pre-registered as a
hypothesis and tested.

On a confirmed-armed boot, the DSP was fully reset without rebooting, by swapping the audio
stack over to the AVS driver — `snd_intel_dspcfg dsp_driver=4`, then `snd_soc_avs`, whose
probe path runs `avs_dsp_core_disable(AVS_MAIN_CORE_MASK)` and a **purge** boot of Linux's
own firmware. Any Windows-resident libraries were destroyed. Then the stack was swapped back.

| stage | raw RMS | HP100 RMS |
|---|---|---|
| pre-test, legacy path | 2167.2 | 1861.9 |
| on the AVS card, DSP path | 9992.6 | 8775.5 |
| **post-reset, legacy path** | 1344.7 | **1050.7** |

Then a full identification run: **match**, on a *different* track from the pre-test control,
so it was reading live room audio and not a cached result.

🔴 **DSP-resident state is excluded.** The loaded libraries are not the mechanism.

(Incidental but useful to anyone testing the AVS driver on this machine: on an armed boot
AVS captures fine, about 8× the legacy path's level, with local playback stopped so there is
no loopback confound. The earlier negative AVS result was measured only on a *dead* boot.)

### 13.6 The power boundary, measured: S3 survives, S4 does not

The state survives S3 suspend, D3, `FUNCTION_RESET`, PCI re-probe and Linux→Linux warm
reboot (§11.9). Hibernation is the interesting case: **S4 writes the image and then removes
power**, so it separates "software reset" from "power removal" precisely.

Real ACPI S4 (`/sys/power/disk` = `platform`, hibernation confirmed by the swap header
having been rewritten with the suspend signature on the way down):

| capture | raw RMS | HP100 RMS | distinct |
|---|---|---|---|
| armed, minutes before | 1410.4 | **627.1** | 9031 |
| after S4 resume | 28.1 | **17.5** | 373 |

🔴 **S4 kills it**, like S5. And a second answer rode along for free: power was out for only
**~30 seconds** and the arming was still gone, so 🔴 **charge or capacitive decay is
excluded** — this is not a rail coasting down slowly, it is a domain that loses power.

That places the state in a domain powered across S3 and dropped at S4/S5 — in PCH terms,
the deep-sleep and suspend wells.

### 13.7 🔴 The deep-well surfaces — including one the kernel could not see

Following §13.6, four surfaces in the right power domain were dumped on a dead boot and again
on an armed one. One of them had never been readable by any earlier capture in this project,
and finding that was the only genuinely *positive* localisation the investigation produced.

#### The blind spot was real

`INT344B:00` — the pinctrl driver — claims **three** GPIO community apertures in
`/proc/iomem`: `fdac0000`, `fdae0000`, `fdaf0000`. The fourth, **`fdad0000`, is claimed by
`PNP0C02:00`**, the generic motherboard-resources placeholder, and is never bound by
pinctrl. Verified rather than inferred:

* `gpiochip0` reports **152** GPIOs. This PCH has **164** — 152 in GPP_A–G plus 12 in GPD.
* All 12 GPD signal names — `SLP_S3`, `SLP_S4`, `SLP_A`, `SUSCLK`, `SLP_WLAN`, `SLP_S5`,
  `ACPRESENT`, `LANPHYPC` and the rest — return **zero hits** in the pinctrl `pins` file.
* Reading `fdad0000` directly shows the standard Intel community layout (`PADBAR` at `+0x0c`
  = `0x400`) with **exactly 12 pad-config pairs** at `fdad0400`–`fdad0458`. 12 pads = GPD.

**GPD is the group in the deep-sleep well** — powered across S3, dropped at S4/S5. That is
precisely the signature §13.6 established. And every "pinctrl is byte-identical" claim in
§12.2 was blind to it, because `capture-platform-state.sh` reads the pinctrl driver's own
files and the driver does not own that aperture.

#### And it is negative anyway

`dump-four-surfaces.sh` reads all four communities' full 64 KiB apertures through
`/dev/mem`, plus the PMC, the EC's 256 bytes of RAM and the I²C enumeration. Dead baseline
and armed dump, positive control on the armed boot first (correct track identified from
**8 seconds** of room audio — raw RMS 959, 7639 distinct values):

| surface | armed vs dead |
|---|---|
| `fdad0000` — the 12 GPD pads pinctrl never binds | **md5-identical** |
| `fdac0000` / `fdae0000` / `fdaf0000` | **md5-identical** |
| PMC (`pmc_core`) | identical but for the free-running Package C2–C9 residency counters |
| I²C enumeration | identical but for an `i2c-5`/`i2c-6` probe-order swap |
| EC RAM | 25 bytes differ — see below |

🔴 **No PCH GPIO pad state and no PMC state carries the arming.**

#### The EC very nearly produced a false positive

EC RAM had no established noise floor, so one was measured: nine further samples across
three minutes **on the same armed boot**. Nineteen of the 25 differing bytes move on their
own. The 13 survivors looked exactly right — host-written, zero after hibernation, non-zero
after a Windows warm reboot.

The DSDT names them. `Field (ECOR)` gives `0x49` as AC-adapter and link bits, and
`0xd6`–`0xe1` as six 16-bit **subsystem power-budget limits** — `CPLO/CPHI`, `PCLO/PCHI`,
`WLLO/WLHI`, `MELO/MEHI`, `CGLO/CGHI`, `SDLO/SDHI` — all `0x0000` → `0x05c7`. Six power caps
and a charger descriptor, on a boot that was on mains against a baseline that was not.

🔴 Not an audio carrier. **The lesson generalises: decode EC offsets against the DSDT before
believing any EC delta.** [tools/ec-analyse.py](tools/ec-analyse.py) does the floor
intersection.

### 13.8 Where this leaves it

The user-facing answer is unchanged and still works: **boot Windows once per power cycle,
warm-reboot into Linux, and the internal microphone records real audio on a stock kernel.**

The root cause is open, and the space left to search is now small and awkward. Closed
surfaces, none of which a reader should spend time on:

| surface | result |
|---|---|
| ~2400 codec registers, all 8 vendor COEF banks | zero separate working from dead |
| the codec tree / topology | identical |
| codec verbs as static state **and** as ordered sequence | negative |
| 152 pinctrl pads, PCI config space, ACPI, clock tree | identical |
| **the full 16 KiB HDA BAR0**, `LCTL`/`SCF`, `PPCTL`/`GPROCEN` | identical / negative |
| **the DSP** — resident state, loaded libraries | survives a full core reset ⇒ excluded |
| **all four GPIO communities, including the unbound GPD deep-well pads** | identical |
| **the PMC**, the EC, I²C enumeration | identical / explained |
| firmware, BIOS, ME acting alone | excluded by A2 |
| a slowly-decaying rail or stored charge | excluded — 30 s off is enough to kill it |

What is *established*, positively:

1. The audio path is **the codec over the HD-audio link**, on both operating systems. Not
   the SoC's PDM interface (§13.4).
2. `RTKVHD64.sys` is **necessary**; the DSP alone is **not sufficient** (§13.2).
3. Its **codec verbs are not the mechanism** (§13.3) — so whatever it does, it does over DSP
   IPC or some other channel.
4. The state lives in a domain **powered across S3 and lost at S4/S5**, and is not carried by
   any register, pad, or memory this project has been able to read (§13.6, §13.7).

That combination is genuinely strange, and it is the reason this is being published rather
than solved. Something that survives a full codec re-initialisation, a full DSP core reset,
and a warm reboot, but dies within 30 seconds of power removal, and is invisible in every
readable register on the platform.
