#!/bin/sh
# Private SDK only. Never install a profile into the real system data directory.
set -eu
test "${EQ_PRIVATE_TEST:-}" = 1
test ! -e /dev/snd
test -f "${EQ_OEM_RULE:?Pass the reviewed OEM 51 WirePlumber rule for ordering checks}"
test -f "${EQ_OEM_PROFILE:?Pass the matching reviewed OEM profile}"
daemon_source=${1:?Pass the absolute companion EQ daemon source directory}
cd "$(dirname "$0")/.."
profile_root=$(mktemp -d /root/elementary-eq-bridge.XXXXXX)
trap 'rm -rf "$profile_root"' EXIT
mkdir -p tests/schemas
cp "$daemon_source/data/io.elementary.settings-daemon.gschema.xml" tests/schemas/
glib-compile-schemas tests/schemas
wp_prefix=${EQ_WP_PREFIX:-/usr}
mkdir -p tests/wp-vapi
vapigen --library=wireplumber-0.5 --pkg=gio-2.0 --metadatadir="$daemon_source/vapi" \
    --directory=tests/wp-vapi "$wp_prefix/share/gir-1.0/Wp-0.5.gir" > tests/wp-vapi/build.log 2>&1
cc -g -fsanitize=address -fno-omit-frame-pointer -DGETTEXT_PACKAGE=\"io.elementary.settings-daemon\" "-DEQ_PROFILE_DIR=\"$profile_root/v1\"" \
    -c "$daemon_source/src/Backends/speaker-equalizer-profile.c" \
    $(pkg-config --cflags gio-2.0) -o tests/bridge-profile.o
cc -g "$daemon_source/tests/graph-rules.c" $(pkg-config --cflags --libs wireplumber-0.5) -o tests/graph-rules
cc -g "$daemon_source/tests/bridge-device.c" $(pkg-config --cflags --libs libpipewire-0.3) -o tests/bridge-device
valac --pkg libpulse --pkg libpulse-mainloop-glib --pkg gio-2.0 --pkg libpulse-operation \
    --pkg speaker-equalizer-profile --pkg wireplumber-0.5 --vapidir="$daemon_source/vapi" --vapidir=tests/wp-vapi \
    -X '-DGETTEXT_PACKAGE="io.elementary.settings-daemon"' -X "-I$daemon_source/src" \
    -X "-I$wp_prefix/include/wireplumber-0.5" -X "-L$wp_prefix/lib/x86_64-linux-gnu" \
    -X -fsanitize=address -X -fno-omit-frame-pointer -X -g \
    -X tests/bridge-profile.o -X -lwireplumber-0.5 -X -lm -o tests/bridge-audio-owner \
    "$daemon_source/src/Backends/EchoProcessor.vala" "$daemon_source/src/Backends/Audio.vala" \
    "$daemon_source/src/Backends/SpeakerEqualizer.vala" tests/aec-regression/audio-owner.vala \
    > tests/bridge-owner-build.log 2>&1
valac --pkg gtk4 --pkg granite-7 --pkg gee-0.8 --pkg libpulse --pkg gio-2.0 --pkg json-glib-1.0 \
    -X '-DGETTEXT_PACKAGE="io.elementary.settings.sound"' -o tests/bridge-client \
    src/SpeakerEqualizer.vala src/SpeakerEqualizerPanel.vala src/Device.vala src/EchoCancellation.vala \
    tests/bridge-client.vala > tests/bridge-client-build.log 2>&1
ASAN_OPTIONS=detect_leaks=0 EQ_DAEMON_SOURCE="$daemon_source" EQ_TEST_PROFILE_DIR="$profile_root/v1" EQ_TEST_PROFILE="$daemon_source/tests/fixture-v1.ini" \
    python3 tests/active-bridge.py
for scenario in valid oem-valid oem-independent-graph untrusted oem-empty oem-wildcard oem-untrusted invalid-layout; do
    ASAN_OPTIONS=detect_leaks=0 EQ_DAEMON_SOURCE="$daemon_source" EQ_GENERIC_CASE="$scenario" \
        EQ_TEST_PROFILE_DIR="$profile_root/v1" python3 tests/active-bridge.py
done
