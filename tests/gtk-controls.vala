// Actual GTK controls and production model, with a private read-only Audio fixture.
// This does not claim native audio integration or acoustic validation.
[DBus (name = "io.elementary.settings_daemon.Audio")]
public class EqualizerFixture : Object {
    public bool failed { get; set; }
    public bool generic { get; set; }
    public signal void equalizer_changed ();
    public Sound.SpeakerEqualizer.Status get_equalizer_status () throws DBusError, IOError {
        return { !failed, false, false, failed ? "Fixture audit failure" : "",
            "/io/elementary/settings-daemon/audio/equalizer/0000000000000000000000000000000000000000000000000000000000000000/",
            "fixture.output", "fixture-speaker",
            { 105, 190, 280, 2800, 8500 }, { "low-shelf", "low-shelf", "peak", "peak", "high-shelf" },
            generic ? new double[0] : new double[] { -1, -2, -3, -4, -5 }, { -12, -12, -12, -12, -12 }, { 12, 12, 12, 12, 12 } };
    }
}

int main () {
    assert (Environment.get_variable ("GSETTINGS_BACKEND") == "memory");
    assert (Environment.get_variable ("EQ_PRIVATE_TEST") == "1");
    Gtk.init ();
    var loop = new MainLoop ();
    var service = new EqualizerFixture ();
    uint owner = Bus.own_name (SESSION, "io.elementary.settings-daemon", NONE, (connection) => {
        try { connection.register_object ("/io/elementary/settings_daemon", service); }
        catch (Error e) { error (e.message); }
    });
    var prefs = new Settings.with_path ("io.elementary.settings-daemon.audio.equalizer",
        "/io/elementary/settings-daemon/audio/equalizer/0000000000000000000000000000000000000000000000000000000000000000/");
    var panel = new Sound.SpeakerEqualizerPanel ();
    var device = new Sound.Device ("fixture", 42, "fixture-speaker") { card_sink_name = "fixture.output" };
    panel.set_device (device);
    var window = new Gtk.Window () { child = panel, default_width = 600, default_height = 450 };
    var header = (Gtk.Box) panel.get_first_child ();
    var toggle = (Gtk.Switch) header.get_last_child ();
    var bands = (Gtk.Grid) header.get_next_sibling ();
    var reset = (Gtk.Button) bands.get_next_sibling ();
    var slider = (Gtk.Scale) bands.get_child_at (1, 0);
    var feedback = (Gtk.Label) reset.get_next_sibling ();
    uint phase = 0;
    window.present ();
    Timeout.add (50, () => {
        if (phase == 0 && toggle.sensitive) {
            assert (!toggle.active);
            toggle.activate ();
            device.notify_property ("description"); // Ordinary device refresh during the switch animation.
            phase++;
        } else if (phase == 1 && prefs.get_boolean ("enabled")) {
            assert (toggle.active && bands.sensitive);
            string[] expected_labels = { "Bass", "Low mids", "Mids", "Air", "Upper balance" };
            string[] expected_tooltips = { "105 Hz", "190 Hz", "280 Hz", "2800 Hz", "8500 Hz" };
            for (int i = 0; i < 5; i++) {
                var scale = (Gtk.Scale) bands.get_child_at (1, i);
                assert (scale.adjustment.lower == -12 && scale.adjustment.upper == 12);
                var label = (Gtk.Label) bands.get_child_at (0, i);
                assert (label.label == expected_labels[i]);
                assert (label.tooltip_text == expected_tooltips[i]);
            }
            assert (!feedback.visible);
            print ("PASS fixed names, profile frequency tooltips, symmetric ranges and no idle status message\n");
            print ("PASS native GTK enable and sensitivity\n");
            slider.set_value (-6);
            assert (prefs.get_value ("gains").get_child_value (0).get_double () == -6);
            print ("PASS gain slider writes the saved bounded array\n");
            reset.clicked ();
            assert (slider.get_value () == -1 && toggle.active);
            print ("PASS Reset restores recommendations and preserves On\n");
            device.card_sink_name = "other.output";
            assert (!toggle.sensitive && !bands.sensitive);
            device.card_sink_name = "fixture.output";
            assert (toggle.sensitive);
            print ("PASS physical output mismatch disables controls\n");
            service.failed = true;
            service.equalizer_changed ();
            phase++;
        } else if (phase == 2 && !reset.sensitive) {
            assert (toggle.active && toggle.sensitive && !bands.sensitive && !reset.sensitive);
            assert (feedback.visible && feedback.label == "Fixture audit failure");
            slider.set_value (-6);
            assert (prefs.get_value ("gains").get_child_value (0).get_double () == -1);
            print ("PASS unsupported status permits withdrawal and refuses gain changes\n");
            toggle.activate ();
            device.notify_property ("description");
            phase++;
        } else if (phase == 3 && !prefs.get_boolean ("enabled")) {
            assert (!toggle.active && !toggle.sensitive);
            print ("PASS failed-status Off withdraws saved enable preference\n");
            toggle.active = true;
            assert (!prefs.get_boolean ("enabled"));
            print ("PASS failed-status enable remains refused\n");
            service.generic = true;
            service.failed = false;
            service.equalizer_changed ();
            phase++;
        } else if (phase == 4 && toggle.sensitive && !toggle.active) {
            phase++;
        } else if (phase == 5 && reset.sensitive && !toggle.active) {
            reset.clicked ();
            assert (slider.get_value () == 0 && !toggle.active);
            toggle.active = true;
            slider.set_value (-6);
            assert (prefs.get_value ("gains").get_child_value (0).get_double () == -6);
            toggle.active = false;
            assert (slider.get_value () == -6 && bands.sensitive);
            reset.clicked ();
            assert (slider.get_value () == 0 && !toggle.active);
            print ("PASS generic sliders, Off retains gains, Reset restores zero and preserves Off\n");
            Bus.unown_name (owner);
            phase++;
        } else if (phase == 6 && !toggle.sensitive) {
            print ("PASS service disappearance disables controls\n");
            window.destroy ();
            loop.quit ();
            return Source.REMOVE;
        }
        return Source.CONTINUE;
    });
    Timeout.add_seconds (8, () => { error ("GTK controls timeout at phase %u", phase); });
    loop.run ();
    return 0;
}
