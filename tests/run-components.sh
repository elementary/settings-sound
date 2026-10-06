#!/bin/sh
# Run in an isolated SDK copy with the companion daemon source as argument.
set -eu
test "${EQ_PRIVATE_TEST:-}" = 1
test ! -e /dev/snd
daemon_source=${1:?Pass the absolute companion EQ daemon source directory}
cd "$(dirname "$0")/.."
mkdir -p tests/schemas validation
cp "$daemon_source/data/io.elementary.settings-daemon.gschema.xml" data/sound.gschema.xml tests/schemas/
glib-compile-schemas tests/schemas
valac --pkg gio-2.0 -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' \
    -o tests/generic-equalizer src/SpeakerEqualizer.vala tests/generic-equalizer.vala
mkdir -p tests/model-schemas
cp "$daemon_source/data/io.elementary.settings-daemon.gschema.xml" tests/model-schemas/
printf '[io.elementary.settings-daemon.audio.equalizer]\nenabled=true\n' > tests/model-schemas/91-vendor.gschema.override
glib-compile-schemas tests/model-schemas
GSETTINGS_BACKEND=memory GSETTINGS_SCHEMA_DIR="$PWD/tests/model-schemas" \
    dbus-run-session -- tests/generic-equalizer
valac --pkg gtk4 --pkg granite-7 --pkg gee-0.8 --pkg libpulse --pkg gio-2.0 \
    -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' -o tests/gtk-controls \
    src/SpeakerEqualizer.vala src/SpeakerEqualizerPanel.vala src/Device.vala tests/gtk-controls.vala \
    > tests/gtk-build.log 2>&1
GSETTINGS_BACKEND=memory GSETTINGS_SCHEMA_DIR="$PWD/tests/schemas" GTK_A11Y=none \
    dbus-run-session -- xvfb-run -a tests/gtk-controls > tests/gtk-controls.log 2>&1

# The combined bridge builds the production owner through generated WP bindings.
sh tests/run-active-bridge.sh "$daemon_source"
cp tests/bridge-audio-owner tests/aec-regression/audio-owner
valac --pkg gio-2.0 --pkg json-glib-1.0 -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' \
    -o tests/aec-regression/echo-client src/EchoCancellation.vala tests/aec-regression/echo-client.vala \
    > tests/echo-client-build.log 2>&1
valac --pkg libpulse --pkg libpulse-mainloop-glib -o tests/aec-regression/stream-client \
    tests/aec-regression/stream-client.vala > tests/stream-client-build.log 2>&1
valac --pkg gtk4 --pkg granite-7 --pkg switchboard-3 --pkg gee-0.8 --pkg libpulse --pkg libpulse-mainloop-glib --pkg gio-2.0 \
    --pkg libpulse-ext --vapidir=vapi -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' \
    -o tests/aec-regression/ui-client src/EchoCancellation.vala src/PulseAudioManager.vala src/InputPanel.vala \
    src/InputDeviceMonitor.vala src/Device.vala src/DeviceRow.vala src/App.vala tests/aec-regression/ui-client.vala \
    > tests/aec-ui-build.log 2>&1
AEC_WITH_EQ=1 python3 tests/aec-regression/run-functional.py pulse > tests/aec-pulse.log 2>&1
AEC_WITH_EQ=1 python3 tests/aec-regression/run-functional.py pipewire > tests/aec-pipewire.log 2>&1
