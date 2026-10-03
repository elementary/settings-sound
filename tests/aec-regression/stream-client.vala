// Real libpulse streams, explicitly pinned with PA_STREAM_DONT_MOVE.
int main (string[] args) {
    assert (Environment.get_variable ("PULSE_SERVER").has_prefix ("unix:/tmp/vale-sound-"));
    assert (args.length == 4);
    var loop = new MainLoop ();
    var pulse_loop = new PulseAudio.GLibMainLoop ();
    var context = new PulseAudio.Context (pulse_loop.get_api (), "vale-sound-native-streams");
    PulseAudio.Stream? playback = null;
    PulseAudio.Stream? capture = null;
    var sample = PulseAudio.SampleSpec () { format = PulseAudio.SampleFormat.S16NE, rate = 48000, channels = 2 };
    var flags = args[3] == "active" ? (PulseAudio.Stream.Flags) 0 : PulseAudio.Stream.Flags.START_CORKED;
    var playback_flags = flags;
    var capture_flags = flags;
    if (args[3] == "pinned" || args[3] == "playback-pinned") {
        playback_flags |= PulseAudio.Stream.Flags.DONT_MOVE;
    }
    if (args[3] == "pinned" || args[3] == "capture-pinned") {
        capture_flags |= PulseAudio.Stream.Flags.DONT_MOVE;
    }

    bool printed = false;
    context.set_state_callback ((c) => {
        if (c.get_state () != PulseAudio.Context.State.READY) {
            return;
        }

        playback = new PulseAudio.Stream (c, "vale-sound-output", sample);
        capture = new PulseAudio.Stream (c, "vale-sound-input", sample);
        playback.set_write_callback ((s, bytes) => {
            uint8[] silence = new uint8[bytes];
            s.write (silence, bytes);
        });
        capture.set_read_callback ((s, bytes) => {
            void* data;
            size_t length;
            if (s.peek (out data, out length) == 0) {
                s.drop ();
            }
        });
        playback.set_state_callback ((s) => {
            if (!printed && capture.get_state () == PulseAudio.Stream.State.READY && s.get_state () == PulseAudio.Stream.State.READY) {
                stdout.printf ("%u %u\n", playback.get_index (), capture.get_index ());
                stdout.flush ();
                printed = true;
            }
        });
        capture.set_state_callback ((s) => {
            if (!printed && playback.get_state () == PulseAudio.Stream.State.READY && s.get_state () == PulseAudio.Stream.State.READY) {
                stdout.printf ("%u %u\n", playback.get_index (), capture.get_index ());
                stdout.flush ();
                printed = true;
            }
        });
        assert (playback.connect_playback (args[2], null, playback_flags) == 0);
        assert (capture.connect_record (args[1], null, capture_flags) == 0);
    });
    assert (context.connect (Environment.get_variable ("PULSE_SERVER"), PulseAudio.Context.Flags.NOAUTOSPAWN) == 0);
    var input = new IOChannel.unix_new (0);
    input.add_watch (IOCondition.IN | IOCondition.HUP, () => { loop.quit (); return Source.REMOVE; });
    loop.run ();
    playback.disconnect ();
    capture.disconnect ();
    context.disconnect ();
    return 0;
}
