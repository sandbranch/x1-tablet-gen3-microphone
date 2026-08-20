# Findings

Research record for the internal microphone of the ThinkPad X1 Tablet 3rd gen
(20KJ / 20KK), Realtek ALC295, HDA controller `17aa:2244`. Kernel 7.0, Ubuntu.

The bug is **not solved**. This documents what is established, what is excluded, and
what is left — including two results that were published here and later retracted.

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

## 2. Topology, and what the generic parser does with it

The ALC295 has three input converters:

    ADC 0x07  <- Audio Selector 0x24  <- 0x12* 0x13 0x18      rates: 48000 ONLY
    ADC 0x08  <- Audio Mixer    0x23  <- 0x19 0x1a 0x1b 0x1d 0x12
    ADC 0x09  <- Audio Mixer    0x22  <- 0x19 0x1a 0x1b 0x1d 0x13   (fully muted)

Selector `0x24` already selects `0x12`, and ADC `0x07` supports a single fixed rate —
the signature of a PDM decimation path. So `0x12 -> 0x24 -> 0x07` is the dedicated
digital-microphone path.

Linux exposes exactly one capture PCM, on ADC `0x08`. The reason is in
`sound/hda/codecs/generic.c` — the parser filters out ADCs that cannot reach every active
input pin, and ADC `0x07` cannot reach pin `0x19`, the headset mic. So it keeps `0x08`
and drops `0x07`, and the digital pin gets read through the **analog** mixer.

This can be overridden with a pin-config patch that disables `0x19`, after which the
parser selects ADC `0x07` (confirmed: during capture `0x07 conv=0x10`, `0x08`/`0x09`
idle). It does not help — see §4 — but it is a useful oracle.

## 3. ⭐ The noise is a floating analog input — `COEF 0x08` bits 2+3

**This is the main result.**

    COEF 0x08 = 0x6a8c   (Linux)    -> broadband noise, rms ~153, sustained
    COEF 0x08 = 0x6a00   (Windows)  -> EXACT digital silence

Measured on the normal capture path (ADC `0x08`, stock pin config). A 12-second capture
in the Windows configuration contained **2 304 000 data bytes, not one of them non-zero**.

Bit map, two rounds, 3-second captures with 500 ms of head discarded, both rounds agreeing:

    0x6a0c  (bits 2+3)      -> noise, sustained
    0x6a8c  (Linux)         -> noise, sustained
    0x6a00 0x6a80 0x6a08 0x6a04 0x6a84 0x6a88  -> exact silence

**Bits 2 and 3 must both be set for the analog input to pass.** Bit 7 is irrelevant to it.

### The control that makes this safe to believe

With the bits cleared (silence), enabling the codec's internal DAC→ADC loopback and
playing a 1 kHz tone gives **rms 32621, peak 32768, dominant peak 1000.0 Hz**.

⇒ The ADC, its DMA and the whole capture chain are **alive** with the bits cleared. Those
bits gate the analog *source*, not the converter. The silence is a real disconnect.

### Why it matters

The "flat white noise" that defines this bug is an unconnected analog input being
sampled. It is not an undecimated PDM bitstream, not a badly-clocked microphone, and not
mic data of any kind. Any spectral argument about it — including the rise toward Nyquist,
which looks exactly like sigma-delta noise shaping — is analysing nothing.

Windows disables the analog path because it reads this microphone digitally.

## 4. ⭐ Method: init-time COEF writes reach state that live writes cannot

The finding in §3 was only reachable because the Windows register values were applied
**at codec init**, via hda patch firmware, instead of being written live to a running
codec.

Of the 14 registers that differ between Linux and Windows, 12 took at init — including
`0x3a` and `0x40`, which had come back **`STUCK`** (write ignored) on live writes. Two
registers, `0x2b` and `0x67`, never take by either route.

    [codec]
    0x10ec0295 0x17aa2263 0

    [verb]
    0x20 0x500 0x08        # SET_COEF_INDEX 0x08
    0x20 0x400 0x6a00      # SET_PROC_COEF

Loaded with `modprobe snd_hda_intel patch=<file>.fw`.

Anyone replaying vendor register state on an HDA codec should do it this way. A live
write test can return a false negative purely because the register is latched after init.

## 5. What Windows does — the whole stack, taken apart

Windows records this microphone correctly, so it is a working reference implementation.
Every layer of it was examined for a per-machine configuration, and **there is none**:

| source | result |
|---|---|
| `RTKVHD64.sys` pin-config tables | all gated on Realtek **reference-board** SSIDs (`10EC10AE`, `10EC108C`, …) via `SET_SUBSYSTEM_ID`. Never matches `17AA2263`. |
| `RTKVHD64.sys` vendor COEF inits | one sequence, repeated; contains `0x2d=0x3020`, which **bricks this codec**. Not for the ALC295. |
| `RTAIODAT.DAT` 2018, 19 MB (installed) | `MDTR` format, 1420 platform records. **No `17aa2244`, no `17aa2263`.** |
| `RTAIODAT.DAT` 2020, 39 MB | 1794 records. **Same — absent.** |
| the installed INF | endpoint naming and effects only |
| the OEM extension INF | matches our SSID **exactly** — and installs audio effects only |
| `NHLT` ACPI table | **EndpointCount = 0**, payload `deadbeef` — the same empty table Windows reads |
| a 76 MB ETW audio trace | image-load / CPU trace; **zero HDA verb traffic** |

Windows drives this microphone with **generic runtime behaviour**, not a vendor blob.
There is no magic init sequence to lift out of the driver.

Architecturally, Windows runs the codec under **Intel Smart Sound** (`IntcAudioBus`
running, `HDAudBus` stopped, service `IntcAzAudAddService`, `ForceSST=1`), with
`RTKVHD64.sys` as the miniport. Its per-platform registry key is keyed by the PCI SSID
`17aa2244` and holds runtime state (`Pin12=1`, `ChannelConfig=3`, 48 kHz), not
configuration. The endpoint's default format is 2 ch / 48 000 Hz / 16-bit, mask `0x3`.

## 6. Excluded

* **Hardware.** Three independent X1 Tablet Gen 3 machines show the identical symptom.
* **BIOS.** Broken on 1.28 (2019) and on 1.51 / N1ZET95W (2024-11-15).
* **A PCH digital-microphone path.** `NHLT` declares zero endpoints on both operating
  systems, so there is no DSP-side DMIC — the microphone is on the codec.
* **The DSP/host controller choice.** Forcing Linux onto the Intel AVS DSP
  (`snd-intel-dspcfg dsp_driver=4`) binds `snd_soc_avs`, but capture is spectrum-identical
  and shows zero response to speech: it swaps the host DMA side while the same codec
  driver and parser make the same routing decision.
* **Converter selection.** Forcing the parser onto ADC `0x07` works and yields exact
  zeros. Four stream formats (1/2 ch, 16/24-bit, 48 kHz and even an unadvertised 44.1 kHz)
  all program correctly and all yield zeros.
* **Codec GPIOs.** All disabled, byte-identical on both operating systems.
* **Platform ACPI.** The DSDT (39 450 lines decompiled) contains no microphone device,
  rail or GPIO; the only audio device is `HDAS` with the stock Intel `_DSM`.
* **Static COEF replay.** All 14 measured Windows values, individually and together,
  live and at init — no audio. `alc256_fixup_set_coef_defaults` (`0x10 0x24 0x26 0x29
  0x37 0x45`), whose kernel comment describes this exact symptom, is also negative; on
  this machine Windows holds the *same* values as Linux for `0x10` and `0x45`.

## 7. Two retracted results, and why they survived review

Kept deliberately — both are instructive.

**`COEF 0x07` bit 10 "DMIC clock enable".** It is an internal DAC→ADC loopback. Tone tests
recovered 1 kHz at over a million times the median bin and tracked frequency across two
test tones — and all of it was the machine recording its own playback. See
`retracted/RETRACTED.md`. An earlier candidate had already failed the same way through
speaker bleed. **Two independent traps, each producing a clean frequency match.**

**"The DMIC clock theory is dead."** That was concluded from COEF dumps taken after a
warm reboot from Windows — i.e. *after* the Windows driver ran its shutdown path. Any
register the vendor driver clears on the way out reads identical to never-set. The
measurement could not have detected a stream-scoped enable, so it never established what
it was cited for.

## 8. Traps worth knowing on this codec

* **Mute every output pin before believing any microphone result.** Frequency tracking
  does not distinguish an electrical loopback from an acoustic path.
* **Capture-start transient.** A fresh capture shows rms ≈ 2900, peak 32767 for the first
  few hundred milliseconds regardless of state. It produced a false hit here. Use ≥2 s
  captures, discard ≥500 ms, and require *sustained* frame RMS.
* **"Not zero" is not a signal.** Four apparent hits in a bit sweep were all converter
  artefacts: a stuck DC alternating at Nyquist, a full-scale stuck value, and decaying
  transients. Require: sustained across the window, channels not bit-identical, not a
  fixed alternation at Nyquist, many distinct values.
* **`COEF 0x2d = 0x3020` bricks the codec.** It stops answering; no module reload
  recovers it, only a full power cycle. Never replay a vendor COEF sequence wholesale —
  write one register at a time and verify the codec still answers after each.
* **Live values differ from `probe_only=3` dumps.** `COEF 0x10` reads `0x0120` live and
  `0x0320` with the driver's init suppressed. Do not plan bit tests off a probe-only dump.
* `modprobe -r snd_hda_intel` fails while PipeWire holds the card; it must be **masked**,
  not merely stopped, because socket activation restarts it instantly.

## 9. What is left

The enable for the digital microphone itself. With the analog path disabled — Windows'
own configuration — the capture chain is proven alive and delivers exact zeros, so
nothing is arriving from the PDM source. The static configuration space is exhausted:
Windows holds no per-platform blob, and its post-shutdown register state has been
replayed in full.

That leaves state the vendor driver holds only **while a capture stream is open**, which
no post-hoc dump can see. Capturing it requires reading the codec while Windows is
actively recording.
