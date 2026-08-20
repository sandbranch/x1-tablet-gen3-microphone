# Internal microphone — ThinkPad X1 Tablet 3rd gen (20KJ / 20KK)

**Status: not solved.** This is a research record, not a fix. It is published because
the investigation established several things that are independently useful, and because
the symptom is reported by other owners of this machine with no working answer anywhere.

On this machine the built-in microphone records **broadband noise** under Linux — no
speech, no tone, at any gain. The same microphone records correctly under Windows on the
same hardware, so this is a driver gap, not a hardware fault.

    machine      ThinkPad X1 Tablet 3rd gen, 20KK / 20KJ
    codec        Realtek ALC295, subsystem 0x17aa2263, revision 0x100002
    controller   Intel Sunrise Point-LP HD Audio, PCI SSID 17aa:2244
    internal mic pin 0x12, config 0x90a60130 = internal, Mic In, connection "Other Digital"

## What is established

**The noise is not microphone data.** It is a *floating analog input*. Vendor register
`COEF 0x08` bits 2 and 3 gate the codec's analog input path. Linux leaves them set
(`0x6a8c`), on a pin whose only source is digital — so the ADC samples an unconnected
analog input, which is the hiss. Windows clears them (`0x6a00`) and the same capture
returns **exact digital silence**.

This matters for anyone else debugging this class of bug: the noise carries no
information, and its spectrum (including a rise toward Nyquist that is easy to mistake
for an undecimated PDM bitstream) says nothing about the microphone.

**What is still missing** is the enable for the digital microphone itself. With the
analog path disabled — i.e. in Windows' own configuration — the capture path is proven
alive and delivers exact zeros. Nothing arrives from the PDM source.

Full detail, including everything ruled out and the traps that produced two retracted
results, is in **[FINDINGS.md](FINDINGS.md)**.

## Is this your bug?

    arecord -f S16_LE -r 48000 -c 2 -d 3 /tmp/t.wav

If that gives audible hiss with no speech in it, and:

    cat /proc/asound/card0/codec#0 | head -6      # Realtek ALC295 / 0x17aa2263
    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_COEF_INDEX 0x08
    sudo hda-verb /dev/snd/hwC0D0 0x20 GET_PROC_COEF 0x00
    #   value = 0x6a8c    <- analog input path enabled; this is the noise

then yes.

## Turning the noise off

This is **not a fix** — it replaces noise with silence, and the microphone still does not
work. It is documented only because a microphone that emits hiss into every call is worse
than one that emits nothing, and because it is the cleanest way to confirm the finding on
your own machine.

    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_COEF_INDEX 0x08
    sudo hda-verb /dev/snd/hwC0D0 0x20 SET_PROC_COEF 0x6a00

Capture then returns exact zeros. It does not survive a driver reload or resume; nothing
here is installed persistently on purpose, because silence is not worth a permanent
system change.

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

## Licence

See [LICENSE](LICENSE).
