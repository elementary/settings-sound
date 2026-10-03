// Actual GTK controls and production model, with a private read-only Audio fixture.
// This does not claim native audio integration or acoustic validation.
[DBus (name = "io.elementary.settings_daemon.Audio")]
public class EqualizerFixture : Object {
    public bool failed { get; set; }
    public signal void equalizer_changed ();
    public Sound.SpeakerEqualizer.Status get_equalizer_status () throws DBusError, IOError {
        return { !failed, false, !failed, failed ? "Fixture audit failure" : "",
            "/io/elementary/settings-daemon/audio/equalizer/0000000000000000000000000000000000000000000000000000000000000000/",
            "fixture.output", "fixture-speaker",
            { 100, 250, 1000, 4000, 10000 }, { "low-shelf", "peak", "peak", "peak", "high-shelf" },
            { -1, -2, -3, -4, -5 }, { -12, -12, -12, -12, -12 }, { 0, 0, 0, 0, 0 } };
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
    var choices = (Gtk.Box) header.get_next_sibling ();
    var presets = (Gtk.DropDown) choices.get_first_child ();
    var reset = (Gtk.Button) choices.get_last_child ();
    var bands = (Gtk.Grid) choices.get_next_sibling ();
    var slider = (Gtk.Scale) bands.get_child_at (1, 0);
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
            print ("PASS native GTK enable and sensitivity\n");
            presets.selected = 1;
            assert (prefs.get_string ("preset") == "flat");
            assert (slider.get_value () == 0);
            print ("PASS Flat control\n");
            slider.set_value (-6);
            assert (prefs.get_string ("preset") == "custom");
            assert (prefs.get_value ("gains").get_child_value (0).get_double () == -6);
            print ("PASS gain slider selects Custom and writes bounded array\n");
            reset.clicked ();
            assert (prefs.get_string ("preset") == "device-default");
            assert (slider.get_value () == -1);
            print ("PASS Reset restores device defaults\n");
            device.card_sink_name = "other.output";
            assert (!toggle.sensitive && !bands.sensitive);
            device.card_sink_name = "fixture.output";
            assert (toggle.sensitive);
            print ("PASS physical output mismatch disables controls\n");
            service.failed = true;
            service.equalizer_changed ();
            phase++;
        } else if (phase == 2 && !presets.sensitive) {
            assert (toggle.active && toggle.sensitive && !bands.sensitive && !reset.sensitive);
            presets.selected = 1;
            slider.set_value (-6);
            assert (prefs.get_string ("preset") == "device-default");
            assert (prefs.get_value ("gains").get_child_value (0).get_double () == -1);
            print ("PASS failed status permits only withdrawal, presets and gains fail closed\n");
            toggle.activate ();
            device.notify_property ("description");
            phase++;
        } else if (phase == 3 && !prefs.get_boolean ("enabled")) {
            assert (!toggle.active && !toggle.sensitive);
            print ("PASS failed-status Off withdraws saved enable preference\n");
            toggle.active = true;
            assert (!prefs.get_boolean ("enabled"));
            print ("PASS failed-status enable remains refused\n");
            service.failed = false;
            service.equalizer_changed ();
            phase++;
        } else if (phase == 4 && toggle.sensitive && !toggle.active) {
            Bus.unown_name (owner);
            phase++;
        } else if (phase == 5 && !toggle.sensitive) {
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
