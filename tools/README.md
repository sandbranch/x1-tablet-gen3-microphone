# tools

The instruments this investigation was actually run with. All of them assume the HD-audio
controller at `0000:00:1f.3` and codec `hwC0D0`; adjust if yours differs.

| script | what it does |
|---|---|
| `identify-track.sh [sec] [label]` | The **oracle**. Records from the internal mic at the clean `boost 0` / `capture 63` point, mutes every output pin first, percentile-normalises, and submits to a third-party acoustic fingerprinting service (`songrec`). A working codec returns the correct track; a dead one returns no match. Working ≈ rms 1600–3200 with music in the room, dead ≈ 25. |
| `capture-platform-state.sh LABEL` | Sixteen-file snapshot of the whole platform around the controller: all 152 pinctrl pads, GPIO, PCI config space, clock tree, ACPI, power state, codec tree. ~30 s. Run it **first** on a boot, before anything else touches the machine. |
| `dump-hda-mmio.sh LABEL` | Dumps the controller's **memory-mapped** BAR0 register block, which `lspci -xxxx` does not reach. See the warnings below. |
| `probe-vendor-nodes.sh LABEL` | Full 15-node vendor coefficient dump (`NREG=160` for the wide sweep). |

## Warnings that cost time to learn

- **Never read `/dev/mem` on this platform.** It hard-hangs the machine. `dump-hda-mmio.sh`
  maps `/sys/bus/pci/devices/.../resource0` instead, which is bounded to the BAR.
- **The controller runtime-suspends when idle**, and MMIO reads against a device in D3
  return all-ones. `dump-hda-mmio.sh` forces `power/control=on`, waits for `active`, dumps,
  and restores. A dump taken without that is 16 KiB of `0xff` that looks like data — and
  any two states will "agree" perfectly. Take every side of a comparison the same way.
- **Mask the free-running registers before diffing.** `dump-hda-mmio.sh` takes two
  back-to-back passes and writes whatever differed to `volatile-offsets.txt`: the wall
  clock, the CORB/RIRB ring pointers, and the per-link frame counters.
- **BAR4 is the Intel cAVS DSP aperture.** Reading it while the DSP power domain is gated
  can hang the machine. None of these tools touch it. Decide deliberately before you do.
- **Use mic boost 0, not the driver default of 3.** The default applies about +30 dB to
  this pin and clips roughly 40 % of samples into a DC rail — which silently invalidates
  every level measurement taken through it.
- **Mute the output pins before believing any microphone result.** `COEF 0x07` bit 10 on
  this codec is an internal DAC→ADC loopback, and it produced a completely convincing false
  positive early in this work. `identify-track.sh` mutes them by construction.
- **Measure paired.** Room level varies. A single capture proves nothing; run the control
  and the test back to back.
