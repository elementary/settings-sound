// Smoke test the real InputPanel's switch, including programmatic state updates.
int main () {
    assert (Environment.get_variable ("PULSE_SERVER").has_prefix ("unix:/tmp/vale-sound-"));
    Gtk.init ();
    var panel = new Sound.InputPanel ();
    var window = new Gtk.Window () { child = panel, default_width = 700, default_height = 550 };
    var grid = (Gtk.Grid) panel.get_last_child ();
    var toggle = (Gtk.Switch) grid.get_child_at (1, 0);
    var pam = Sound.PulseAudioManager.get_default ();
    var loop = new MainLoop ();
    uint phase = 0;
    int64 clicked_at = 0;
    pam.start ();
    window.present ();
    Timeout.add (25, () => {
        var controller = pam.echo_cancellation;
        if (controller == null || controller.busy || !controller.available) {
            return Source.CONTINUE;
        }

        if (phase == 0) {
            assert (!toggle.active && toggle.sensitive);
            toggle.activate ();
            clicked_at = get_monotonic_time ();
            phase = 1;
        } else if (phase == 1 && controller.enabled && get_monotonic_time () - clicked_at > 400000) {
            assert (toggle.active);
            toggle.activate ();
            phase = 2;
        } else if (phase == 2 && !controller.enabled) {
            assert (!toggle.active);
            print ("PASS InputPanel switch: native enable/disable, state notifications do not issue new requests\n");
            loop.quit ();
            return Source.REMOVE;
        }

        return Source.CONTINUE;
    });
    Timeout.add_seconds (10, () => {
        var controller = pam.echo_cancellation;
        error ("InputPanel timeout: phase %u, enabled %s, busy %s, available %s, error %s, switch %s, preference %s",
            phase, controller.enabled.to_string (), controller.busy.to_string (), controller.available.to_string (),
            controller.error ?? "none", toggle.active.to_string (),
            new Settings ("io.elementary.settings-daemon.audio").get_boolean ("echo-cancellation").to_string ());
    });
    loop.run ();
    window.destroy ();
    return 0;
}
