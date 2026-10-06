// Exercise the production model on a private session bus without audio devices.
[DBus (name = "io.elementary.settings_daemon.Audio")]
public class GenericEqualizerFixture : Object {
    public bool oem;
    public bool malformed;
    public bool fresh;
    public signal void equalizer_changed ();
    public Sound.SpeakerEqualizer.Status get_equalizer_status () throws DBusError, IOError {
        double[] defaults = new double[0];
        if (malformed) {
            defaults = new double[] { 1 };
        } else if (oem) {
            defaults = new double[] { 7.5, 8, -1.5, 1.5, 0.5 };
        }
        return { true, false, true, "",
            "/io/elementary/settings-daemon/audio/equalizer/000000000000000000000000000000000000000000000000000000000000000" + (fresh ? "1/" : "0/"),
            "fixture.output", "analog-output-speaker",
            { 105, 190, 280, 2800, 8500 }, { "low-shelf", "low-shelf", "peak", "peak", "high-shelf" },
            defaults,
            { -12, -12, -12, -12, -12 }, { 8, 8, 8, 8, 8 } };
    }
}

int main () {
    assert (Environment.get_variable ("GSETTINGS_BACKEND") == "memory");
    var loop = new MainLoop ();
    var fixture = new GenericEqualizerFixture ();
    uint owner = Bus.own_name (SESSION, "io.elementary.settings-daemon", NONE, (connection) => {
        try {
            connection.register_object ("/io/elementary/settings_daemon", fixture);
        } catch (Error e) {
            error (e.message);
        }
    });
    var model = new Sound.SpeakerEqualizer ();
    model.start ();
    uint phase = 0;
    Timeout.add (20, () => {
        if (phase == 0 && model.status.available) {
            assert (model.status.defaults.length == 0 && !model.requested);
            assert (model.get_gains ().length == 5 && model.get_gains ()[0] == 0);
            model.set_band (0, 8);
            model.set_band (0, 9);
            assert (model.get_gains ()[0] == 8 && !model.requested);
            model.enable (true);
            model.enable (false);
            assert (!model.requested && model.get_gains ()[0] == 8);
            print ("PASS generic zero/off defaults, bounded sliders and Off retains gains\n");
            fixture.oem = true;
            fixture.equalizer_changed ();
            phase++;
        } else if (phase == 1 && model.status.defaults.length == 5) {
            assert (!model.requested && model.get_gains ()[0] == 8);
            model.reset ();
            assert (model.get_gains ()[0] == 7.5 && !model.requested);
            print ("PASS policy does not overwrite user values; Reset restores recommendations without enabling\n");
            fixture.fresh = true;
            fixture.equalizer_changed ();
            phase++;
        } else if (phase == 2 && model.requested && model.get_gains ()[0] == 7.5) {
            print ("PASS fresh OEM policy starts enabled with recommended gains\n");
            model.enable (false);
            model.set_band (0, -6);
            fixture.equalizer_changed ();
            phase++;
        } else if (phase == 3 && !model.requested && model.get_gains ()[0] == -6) {
            fixture.malformed = true;
            fixture.equalizer_changed ();
            phase++;
        } else if (phase == 4 && !model.status.available) {
            assert (!model.requested);
            model.enable (true);
            assert (!model.requested);
            print ("PASS malformed declared recommendations fail closed\n");
            model.stop ();
            Bus.unown_name (owner);
            loop.quit ();
            return Source.REMOVE;
        }
        return Source.CONTINUE;
    });
    Timeout.add_seconds (5, () => { error ("Generic model timeout at phase %u", phase); });
    loop.run ();
    return 0;
}
