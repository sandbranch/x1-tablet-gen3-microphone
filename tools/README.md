# tools

The instruments this investigation was actually run with. All of them assume the HD-audio
controller at `0000:00:1f.3` and codec `hwC0D0`; adjust if yours differs.

| script | what it does |
|---|---|
| `identify-track.sh [sec] [label]` | The **oracle**. Records from the internal mic at the clean `boost 0` / `capture 63` point, mutes every output pin first, percentile-normalises, and submits to a third-party acoustic fingerprinting service (`songrec`). A working codec returns the correct track; a dead one returns no match. Working ≈ rms 1600–3200 with music in the room, dead ≈ 25. |
| `capture-platform-state.sh LABEL` | Sixteen-file snapshot of the whole platform around the controller: all 152 pinctrl pads, GPIO, PCI config space, clock tree, ACPI, power state, codec tree. ~30 s. Run it **first** on a boot, before anything else touches the machine. |
| `dump-hda-mmio.sh LABEL` | Dumps the controller's **memory-mapped** BAR0 register block, which `lspci -xxxx` does not reach. See the warnings below. |
| `probe-vendor-nodes.sh LABEL` | Full 15-node vendor coefficient dump (`NREG=160` for the wide sweep). |
| `dump-four-surfaces.sh LABEL` | The four surfaces in the deep-sleep/suspend power domain: **all four** PCH GPIO communities via `/dev/mem` — including `fdad0000`, which `PNP0C02:00` claims and pinctrl never binds, so the 12 GPD deep-well pads live only there and no pinctrl-based capture can see them — plus the PMC, 256 bytes of EC RAM, and I²C enumeration. |
| `ec-analyse.py DEAD ARMED FLOORDIR` | Intersects an EC RAM working-vs-dead delta with a **same-boot volatility floor**, so telemetry cannot masquerade as a finding. Decode whatever survives against the DSDT's `Field (ECOR)` before believing it. |
| `decode-sst-ipc.py` | Decodes an Intel SST/cAVS DSP IPC trace into pipelines, modules, gateways and bindings. Field layouts follow the kernel's own `sound/soc/intel/avs/messages.h`. This is what showed Windows uses `HDA_LINK_INPUT`, not the PDM interface. |
| `replay-corb.py` | Replays a captured Windows CORB ring in true chronological order, read-backs included, decoded with the kernel's own command-packing rule. Refuses to run if the burst would touch either of the two registers known to brick this codec. |
| `analyse-wav.py FILE` | Scores a capture: raw and high-passed RMS, distinct-value count, band energies, modulation depth, voiceband activity, and a speech-envelope test. Written after two false positives; it exists so a recording is judged rather than trusted. |

## Warnings that cost time to learn

- **Do not go exploring in `/dev/mem` on this platform.** Reading arbitrary physical
  addresses hard-hangs the machine — it happened here. `dump-hda-mmio.sh` therefore maps
  `/sys/bus/pci/devices/.../resource0`, which is bounded to the BAR, rather than raw
  physical memory. The one deliberate exception is `dump-four-surfaces.sh`, which does map
  `/dev/mem` read-only at four fixed, known GPIO community bases, because `PNP0C02:00`
  claims the GPD community and no driver exposes it. Known address, read-only, bounded
  length — not a sweep.
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
