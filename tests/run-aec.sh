#!/bin/sh
# Run only in the existing private SDK, without host audio devices.
set -eu
test "${AEC_PRIVATE_TEST:-}" = 1
test ! -e /dev/snd
daemon_source=${1:?Pass the AEC-only daemon revision (without the dependent EQ changes)}
cd "$(dirname "$0")/.."
mkdir -p tests/schemas validation
cp "$daemon_source/data/io.elementary.settings-daemon.gschema.xml" data/sound.gschema.xml tests/schemas/
glib-compile-schemas tests/schemas
valac --pkg libpulse --pkg libpulse-mainloop-glib --pkg gio-2.0 --pkg libpulse-operation \
    --vapidir="$daemon_source/vapi" -X '-DGETTEXT_PACKAGE="io.elementary.settings-daemon"' \
    -o tests/aec-regression/audio-owner "$daemon_source/src/Backends/EchoProcessor.vala" \
    "$daemon_source/src/Backends/Audio.vala" tests/aec-regression/audio-owner.vala
valac --pkg gio-2.0 --pkg json-glib-1.0 -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' \
    -o tests/aec-regression/echo-client src/EchoCancellation.vala tests/aec-regression/echo-client.vala
valac --pkg libpulse --pkg libpulse-mainloop-glib -o tests/aec-regression/stream-client \
    tests/aec-regression/stream-client.vala
valac --pkg gtk4 --pkg granite-7 --pkg switchboard-3 --pkg gee-0.8 --pkg libpulse \
    --pkg libpulse-mainloop-glib --pkg gio-2.0 --pkg libpulse-ext --vapidir=vapi \
    -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' -o tests/aec-regression/ui-client \
    src/EchoCancellation.vala src/PulseAudioManager.vala src/InputPanel.vala \
    src/InputDeviceMonitor.vala src/Device.vala src/DeviceRow.vala src/App.vala \
    tests/aec-regression/ui-client.vala
python3 tests/aec-regression/run-functional.py pulse
python3 tests/aec-regression/run-functional.py pipewire
