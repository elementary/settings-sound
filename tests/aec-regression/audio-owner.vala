// Private component harness: owns the production backend on a private bus.
int main () {
    assert (Environment.get_variable ("PULSE_SERVER").has_prefix ("unix:/tmp/vale-sound-"));
    var loop = new MainLoop ();
    Bus.own_name (SESSION, "io.elementary.settings-daemon", NONE, (connection) => {
        try {
            var audio = new SettingsDaemon.Backends.Audio ();
            connection.register_object ("/io/elementary/settings_daemon", audio);
            audio.start ();
        } catch (Error e) {
            error (e.message);
        }
    });
    loop.run ();
    return 0;
}
