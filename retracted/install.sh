#!/bin/bash
# Install the X1 Tablet Gen 3 internal-microphone fix (no kernel rebuild).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
install -m644 "$HERE/x1-tablet-dmic.fw"   /lib/firmware/x1-tablet-dmic.fw
install -m644 "$HERE/x1-tablet-dmic.conf" /etc/modprobe.d/x1-tablet-dmic.conf
echo "installed:"
echo "  /lib/firmware/x1-tablet-dmic.fw"
echo "  /etc/modprobe.d/x1-tablet-dmic.conf"
echo
echo "Takes effect on the next boot, or right now with:"
echo "  systemctl --user mask --now pipewire.socket pipewire wireplumber pipewire-pulse.socket pipewire-pulse"
echo "  sudo modprobe -r snd_hda_intel && sudo modprobe snd_hda_intel"
echo "  systemctl --user unmask ... && systemctl --user start pipewire.socket wireplumber"
