// Standalone native client for the production EchoCancellation class.
// Run only with the explicitly private socket supplied by run-functional.py.
private MainLoop main_loop;
private Sound.EchoCancellation controller;


private void snapshot () {
    var builder = new Json.Builder ();
    builder.begin_object ();
    builder.set_member_name ("enabled");
    builder.add_boolean_value (controller.enabled);
    builder.set_member_name ("available");
    builder.add_boolean_value (controller.available);
    builder.set_member_name ("busy");
    builder.add_boolean_value (controller.busy);
    builder.set_member_name ("error");
    builder.add_string_value (controller.error ?? "");
    builder.set_member_name ("source");
    builder.add_string_value (controller.source_master ?? "");
    builder.set_member_name ("sink");
    builder.add_string_value (controller.sink_master ?? "");
    builder.end_object ();
    var generator = new Json.Generator ();
    generator.set_root (builder.get_root ());
    stdout.printf ("%s\n", generator.to_data (null));
    stdout.flush ();
}

private void start_client () {
    controller = new Sound.EchoCancellation ();
    var input = new IOChannel.unix_new (0);
    input.add_watch (IOCondition.IN | IOCondition.HUP, (channel, condition) => {
        if (IOCondition.HUP in condition) {
            main_loop.quit ();
            return Source.REMOVE;
        }

        try {
            string line;
            channel.read_line (out line, null, null);
            switch (line.strip ()) {
                case "enable": controller.request (true); break;
                case "disable": controller.request (false); break;
                case "reopen": controller = new Sound.EchoCancellation (); break;
                case "refresh": controller.refresh.begin (); break;
                case "quit": main_loop.quit (); return Source.REMOVE;
            }
        } catch (IOChannelError e) {
            error ("stdin: %s", e.message);
        } catch (ConvertError e) {
            error ("stdin: %s", e.message);
        }

        return Source.CONTINUE;
    });
    Timeout.add (100, () => { snapshot (); return Source.CONTINUE; });
}

int main () {
    var server = Environment.get_variable ("PULSE_SERVER");
    assert (server != null && server.has_prefix ("unix:/tmp/vale-sound-"));
    main_loop = new MainLoop ();
    start_client ();
    main_loop.run ();
    return 0;
}
