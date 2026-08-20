# ⛔ RETRACTED — the "COEF 0x07 bit 10" fix does not work. Do not install it.

Everything in this directory is kept as a record of a **wrong result** and of how it
passed review. It is not a fix. `install.sh` here should not be run.

## The claim

That the ALC295's internal digital microphone is "not clocked" unless vendor register
`COEF 0x07` bit 10 (`0x0400`) is set, and that setting it makes the microphone record
normally. `EVIDENCE.md` reports 1 kHz tones recovered at over a million times the median
spectral bin, frequency-tracking across two test tones, and speaker harmonics.

## Why it is wrong

**`COEF 0x07` bit 10 enables an internal DAC→ADC loopback inside the codec.**

With the bit set, the "microphone" records the codec's own playback path. Every tone
result in `EVIDENCE.md` is the test tone arriving electrically, never acoustically. The
measurements are real; the interpretation was not.

What exposed it: re-running the tone test with **every output pin muted**. A real
acoustic path goes quiet when the speakers are muted. This one got *louder*, and the
recovered waveform was a full-scale square wave (±32767, two distinct sample values) —
a digital signal tapped before the analog output stage, not sound in a room.

The frequency-tracking argument, which was written specifically to be robust against
level artefacts, does not distinguish an electrical loopback from an acoustic path.
Both track frequency perfectly. That was the hole.

An earlier candidate on this machine failed the same way for a different reason
(speaker bleed into the analog front end). Two independent traps, both producing a clean
frequency match.

## What replaced it

The noise is now explained, and it is not this register — see `../FINDINGS.md`.
`COEF 0x08` bits 2+3 gate the **analog input path**; Linux enables it on a pin that has
no analog source, and the "broadband noise" is that floating input being sampled.

## The rule that came out of it

**Mute every output pin and re-run before believing any microphone result on this codec.**
Frequency tracking is necessary but not sufficient. A tone that survives muted speakers
is acoustic; a tone that does not is your own playback path.
