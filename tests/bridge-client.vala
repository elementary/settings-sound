// Real Sound model on the private bridge's session bus and GSettings backend.
private Sound.SpeakerEqualizer model;
private MainLoop loop;
private Sound.EchoCancellation echo;
private Gtk.Switch toggle;
private Gtk.Button reset;
private Gtk.Grid bands;
private Sound.SpeakerEqualizerPanel panel;

private void snapshot () {
    var s = model.status;
    var b = new Json.Builder ();
    b.begin_object ();
    b.set_member_name ("available"); b.add_boolean_value (s.available);
    b.set_member_name ("busy"); b.add_boolean_value (s.busy);
    b.set_member_name ("applied"); b.add_boolean_value (s.applied);
    b.set_member_name ("enabled"); b.add_boolean_value (model.requested);
    b.set_member_name ("gains"); b.begin_array ();
    foreach (double gain in model.get_gains ()) {
        b.add_double_value (gain);
    }
    b.end_array ();
    b.set_member_name ("error"); b.add_string_value (s.error);
    b.set_member_name ("node"); b.add_string_value (s.node);
    b.set_member_name ("route"); b.add_string_value (s.route);
    b.set_member_name ("defaults_count"); b.add_int_value (s.defaults.length);
    b.set_member_name ("gtk_on"); b.add_boolean_value (toggle.active);
    b.set_member_name ("gtk_switch_sensitive"); b.add_boolean_value (toggle.sensitive);
    b.set_member_name ("gtk_bands_sensitive"); b.add_boolean_value (bands.sensitive);
    b.set_member_name ("aec_available"); b.add_boolean_value (echo.available);
    b.set_member_name ("aec_enabled"); b.add_boolean_value (echo.enabled);
    b.set_member_name ("aec_busy"); b.add_boolean_value (echo.busy);
    b.set_member_name ("aec_error"); b.add_string_value (echo.error ?? "");
    b.end_object ();
    var generator = new Json.Generator ();
    generator.set_root (b.get_root ());
    print ("%s\n", generator.to_data (null));
    stdout.flush ();
}

int main () {
    assert (Environment.get_variable ("EQ_PRIVATE_TEST") == "1");
    Gtk.init ();
    model = new Sound.SpeakerEqualizer ();
    echo = new Sound.EchoCancellation ();
    panel = new Sound.SpeakerEqualizerPanel ();
    bool generic = Environment.get_variable ("EQ_TEST_GENERIC") == "1";
    var device = new Sound.Device ("fixture", 42, generic ? "analog-output-speaker" : "fixture-speaker") {
        card_sink_name = generic ? "alsa_output.pci-0000_00_1f.3.analog-stereo" : "elementary.eq.test"
    };
    panel.set_device (device);
    var window = new Gtk.Window () { child = panel, default_width = 600, default_height = 450 };
    var header = (Gtk.Box) panel.get_first_child ();
    toggle = (Gtk.Switch) header.get_last_child ();
    reset = (Gtk.Button) header.get_next_sibling ();
    bands = (Gtk.Grid) reset.get_next_sibling ();
    window.present ();
    loop = new MainLoop ();
    model.changed.connect (snapshot);
    var input = new IOChannel.unix_new (0);
    input.add_watch (IOCondition.IN | IOCondition.HUP, (channel, condition) => {
        if (IOCondition.HUP in condition) { loop.quit (); return Source.REMOVE; }
        string line;
        try { channel.read_line (out line, null, null); }
        catch (Error e) { error (e.message); }
        line = line.strip ();
        if (line == "on") model.enable (true);
        else if (line == "off") model.enable (false);
        else if (line == "zero") {
            for (int band = 0; band < 5; band++) {
                model.set_band (band, 0);
            }
        }
        else if (line == "reset") model.reset ();
        else if (line == "gain") model.set_band (0, -6);
        else if (line == "invalid-gains") {
            model.set_band (0, double.parse ("nan"));
            model.set_band (0, 1000);
            model.set_band (-1, -6);
        }
        else if (line == "gtk-toggle") {
            toggle.activate ();
            device.notify_property ("description"); // Refresh must not cancel the user's pending toggle.
        }
        else if (line == "gtk-zero") {
            for (int band = 0; band < 5; band++) {
                ((Gtk.Scale) bands.get_child_at (1, band)).set_value (0);
            }
        }
        else if (line == "gtk-reset") reset.clicked ();
        else if (line.has_prefix ("gtk-gain ")) {
            string[] words = line.split (" ");
            ((Gtk.Scale) bands.get_child_at (1, int.parse (words[1]))).set_value (double.parse (words[2]));
        }
        else if (line.has_prefix ("select-output ")) {
            string[] words = line.split (" ");
            device = new Sound.Device ("fixture", 42, words[2]) { card_sink_name = words[1] };
            panel.set_device (device);
        }
        else if (line == "aec-on") echo.request (true);
        else if (line == "aec-off") echo.request (false);
        else if (line == "quit") { loop.quit (); return Source.REMOVE; }
        snapshot ();
        return Source.CONTINUE;
    });
    model.start ();
    Timeout.add (100, () => { snapshot (); return Source.CONTINUE; });
    loop.run ();
    window.destroy ();
    model.stop ();
    return 0;
}
