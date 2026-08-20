# Evidence

All measurements from the machine this was developed on: ThinkPad X1 Tablet 3rd gen
(20KK), Ubuntu, kernel 7.0.0-29-generic, Realtek ALC295, HDA controller `17aa:2244`.

Method throughout: play a known tone through the machine's own speakers while recording
from the internal microphone, then look for a spectral peak **at that exact frequency**.
Peaks are reported as a multiple of the spectrum's median bin, which makes a real tone
(hundreds of thousands) impossible to confuse with a noise floor (single digits to a few
hundred).

Loudness is not evidence. A broken microphone gets louder when you raise the gain, and
its noise floor changes shape when you touch the analog front end. Only frequency
tracking distinguishes the two, and it was worth being strict about — several earlier
candidate fixes on this machine looked convincing on level alone and were wrong.

## 1. The A/B, single run, gains held constant

Capture on the DMIC's own converter, 1 kHz tone playing throughout:

    COEF 0x07 = 0x0200 (stock)  + tone   ->  every sample exactly 0
    COEF 0x07 = 0x0400          + tone   ->  1 kHz bin  1 026 507x median
    COEF 0x07 = 0x0600          + tone   ->  1 kHz bin  1 318 429x median
    COEF 0x07 = 0x0400 / 0x0600, silence ->  1 kHz bin        0.1x median

## 2. Frequency tracking, default gains

    1000 Hz tone
        1000.0 Hz   2890223.0x median
        3000.0 Hz    586734.8x median     <- odd harmonics: speaker distortion
        5000.0 Hz     64782.4x median

    2500 Hz tone
        2500.0 Hz   1383873.9x median
        7500.0 Hz    263294.0x median

    silence
       16054.0 Hz       240.2x median     <- clock comb, ~2293 Hz spacing
        2293.4 Hz        21.4x median

## 3. The stock capture path, no overrides at all

The fix does not require routing capture to the DMIC's dedicated converter. On the
stock driver with no pin override, capture running on the normal analog ADC:

    COEF 0x07 = 0x0200  + 1 kHz tone  ->  no tone; 1/f noise, top bin 53.4 Hz at 9x
    COEF 0x07 = 0x0600  + 1 kHz tone  ->  1000.0 Hz at 820 578x median

## 4. End to end, ordinary userspace

Recorded through PipeWire from the default source, patch firmware applied at module
load, nothing else changed:

    1000.0 Hz    68330.6x median
    3000.0 Hz    24400.1x median

Capture controls all present and unchanged:

    Simple mixer control 'Mic Boost',0
    Simple mixer control 'Capture',0
    Simple mixer control 'Internal Mic Boost',0

## 5. Survives runtime power-save

`power_save=1`, 15 s idle (the codec closes the stream and powers down), then record:

    COEF 0x07 still 0x600;  1000.0 Hz at 74 249.7x median

## 6. Survives S3

Real deep suspend, 34 s down:

    PM: suspend entry (deep)
    PM: suspend exit

    after resume:  COEF 0x07 = 0x600,  1000.0 Hz at 89 612.0x median

And the discriminating test — is the register *re-applied*, or merely retained across
the sleep? Clear it immediately before suspending:

    cleared before suspend:  COEF 0x07 = 0x200
    after S3 resume:         COEF 0x07 = 0x600

It is re-applied. The patch-firmware `[verb]` block runs again on codec resume.

## 7. What the codec looks like, for comparison

Pin `0x12` is unambiguously a digital microphone pin — no VREF capability at all, so it
cannot be an analog microphone:

    Node 0x12 [Pin Complex] wcaps 0x40040b: Stereo Amp-In
      Pincap 0x00000020: IN
      Pin Default 0x90a60130: [Fixed] Mic at Int N/A
        Conn = Digital

The ALC295 has three input converters. The one fed from that pin supports a single
sample rate, the signature of a PDM decimation path:

    ADC 0x07  <- Audio Selector 0x24  <- 0x12* 0x13 0x18     rates: 48000 only
    ADC 0x08  <- Audio Mixer    0x23  <- 0x19 0x1a 0x1b 0x1d 0x12
    ADC 0x09  <- Audio Mixer    0x22  <- 0x19 0x1a 0x1b 0x1d 0x13

Linux exposes only `ADC 0x08`, because the generic parser drops converters that cannot
reach every active input pin and `0x07` cannot reach the headset microphone on `0x19`
(`sound/hda/generic.c`, "filter out invalid adc_nids that don't give all active input
pins"). That is worth knowing if you go looking, but it is **not** the bug: once bit 10
is set, the ordinary path in section 3 works fine and the dedicated converter is not
needed.

## 8. The 14-register red herring

For anyone attempting the same oracle method: these are the registers that differed
between the state Windows left behind and the state Linux left behind, on this codec.
Every one of them was written back, alone and in combination, and **none of them does
anything to the microphone**.

    COEF   after Linux   after Windows
    0x08   0x6a8c        0x6a00
    0x0c   0x01ef        0x41ef
    0x24   0x0000        0x002d
    0x26   0x0000        0x0065
    0x28   0x0000        0x2200
    0x29   0x3000        0xa015
    0x2b   0x0000        0x0181
    0x3a   0x0010        0x003e
    0x40   0x8800        0x88f0
    0x44   0x4900        0x4500
    0x48   0xd049        0xd811
    0x49   0x0049        0x0045
    0x62   0x0000        0x0077
    0x67   0x0000        0x1000

`0x24 0x26 0x29` look especially promising, because the kernel's own
`alc256_fixup_set_coef_defaults()` writes exactly the Linux values above and its comment
describes this symptom in reverse. On this machine they do nothing. `0x2b 0x3a 0x40` are
not even writable — they read back unchanged.

**`0x07` was identical on both operating systems, at `0x0200`.** That is the whole
lesson of this file: the oracle sampled the codec minutes after recording had stopped,
so a bit the vendor driver sets on stream start and clears on stream stop could never
have shown up in it.

## 9. One false positive, and how it was caught

During the sweep, `0x67 = 0x1000` produced a capture with `rms 1, peak 1, 2 distinct
values` — ±1 LSB dither, which is precisely the signature of a live converter as opposed
to a hard mute. It looked like the answer.

It did not reproduce: three repeats and three interleaved controls all returned exact
digital zero. A single ±1-LSB capture is noise. Repeat before believing anything.
