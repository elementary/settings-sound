#!/bin/sh
# Compare the same regression fixture with the unmodified approved Audio owner.
set -eu
test "${EQ_PRIVATE_TEST:-}" = 1
test ! -e /dev/snd
daemon_source=${1:?Pass the companion EQ daemon source directory with git history}
cd "$(dirname "$0")/.."
git -C "$daemon_source" show 59c80f5:src/Backends/Audio.vala > tests/aec-regression/Audio-baseline.vala
valac --pkg libpulse --pkg libpulse-mainloop-glib --pkg gio-2.0 --pkg libpulse-operation \
    --vapidir="$daemon_source/vapi" -X '-DGETTEXT_PACKAGE="io.elementary.settings-daemon"' \
    -o tests/aec-regression/audio-owner-baseline "$daemon_source/src/Backends/EchoProcessor.vala" \
    tests/aec-regression/Audio-baseline.vala tests/aec-regression/audio-owner.vala > tests/baseline-build.log 2>&1
AEC_BASELINE=1 python3 tests/aec-regression/run-functional.py pipewire > tests/aec-pipewire-baseline.log 2>&1
