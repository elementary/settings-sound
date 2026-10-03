# Speaker EQ companion requirement

This `speaker-eq` change, based on `08b0dd6`, needs the matching settings-daemon
EQ change based on `59c80f5`, including its relocatable
`io.elementary.settings-daemon.audio.equalizer` schema and the existing Audio
object's `GetEqualizerStatus` and `EqualizerChanged` additions. The original
AEC API is unchanged. Missing schema/service/method disables EQ controls.
The distribution must add the matching runtime dependency when these reviewed
changes receive release versions; no speculative version or packaging change
is made here. There is no new Sound build dependency.

Controls write preferences only. Device Default uses immutable profile factory
gains. Off/Flat sends zero gains and unity headroom through the daemon. Editing one of five sliders selects Custom.
Reset restores factory gains/Device Default without toggling enable. Frequency,
Q and headroom have no editable controls. The panel must match the daemon's
physical output and route before enabling controls; closing it drops its bus
watch. Idle readback is shown as waiting, not applied.

The daemon contract is `docs/speaker-equalizer.md` in the companion worktree.
Enabled Device Default/Custom uses fixed profile attenuation; Off/Flat restores
pre-graph loudness within the declared graph contract. Failed native status
still permits Off to withdraw a valid saved enable preference. Enable, presets
and gains remain unavailable until the daemon reports availability. No real hardware profiles, graph migrations,
acoustic claims, PR, package or publication are part of this author change.

`tests/gtk-controls.vala` exercises actual production widgets and model against
a private read-only Audio fixture and memory GSettings. It is not a native
audio integration test. Both source freezes need two independent security and
human/minimality reviews before PR/package work.

`tests/run-active-bridge.sh <daemon-source>` exercises the production Audio
owner, Vala/libWirePlumber backend, Sound model, actual GTK panel and GSettings against private real
PipeWire/Pulse/WirePlumber. A synthetic SPA Device exports actual card/route
metadata, and the fixture installs the graph. No status service or native
control is mocked in that test. `EQ_LEGACY=1` reproduces the earlier overwrite
using archived old sources; `EQ_TEST_CACHE_PARAMS=1` checks rejection of stale
metadata. The test must run in the isolated SDK with `EQ_PRIVATE_TEST=1` and
no `/dev/snd`. The combined bridge exercises owned AEC concurrently with GTK controls.
Its observed route repair is not a claim of sample-atomic switching.
