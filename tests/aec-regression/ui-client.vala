async void subscribe (PulseAudio.Context context) {
    context.subscribe (PulseAudio.Context.SubscriptionMask.SERVER, (c, success) => {
        assert (success == 1);
        subscribe.callback ();
    });
    yield;
}

async string[] defaults (PulseAudio.Context context) {
    string[] names = {};
    context.get_server_info ((c, info) => {
        if (info != null) {
            names = {info.default_sink_name, info.default_source_name};
        }
        defaults.callback ();
    });
    yield;
    return names;
}

async void save_routes (PulseAudio.Context context, string suffix) {
    var entries = new PulseAudio.ExtStreamRestoreInfo[4];
    string sink = "physical_output" + suffix;
    string source = "physical_input" + suffix;
    for (int i = 0; i < entries.length; i++) {
        entries[i].channel_map.init_stereo ();
        entries[i].volume.set (2, PulseAudio.Volume.NORM);
    }
    entries[0].name = "sink-input-by-application-name:Unrelated saved route";
    entries[0].device = sink;
    entries[1].name = "source-output-by-application-name:Unrelated saved route";
    entries[1].device = source;
    entries[2].name = "sink-input-by-application-name:Processed saved route";
    entries[2].device = Sound.EchoCancellation.SINK_NAME;
    entries[3].name = "source-output-by-application-name:Processed saved route";
    entries[3].device = Sound.EchoCancellation.SOURCE_NAME;
    PulseAudio.ext_stream_restore_write (context, PulseAudio.UpdateMode.REPLACE, entries, 0, (c, success) => {
        assert (success == 1);
        save_routes.callback ();
    });
    yield;
}

async void check_routes (PulseAudio.Context context, string suffix, bool follow_default = false, bool preserve_processing = false) {
    int64 deadline = get_monotonic_time () + 10000000;
    string? sink = null;
    string? source = null;
    string? processed_sink = null;
    string? processed_source = null;
    do {
        int found = 0;
        bool matched = true;
        PulseAudio.ext_stream_restore_read (context, (c, info, eol) => {
            assert (eol >= 0);
            if (eol > 0) {
                check_routes.callback ();
            } else if (info.name == "sink-input-by-application-name:Unrelated saved route") {
                sink = info.device;
                matched &= info.device == "physical_output" + suffix || (follow_default && info.device == null);
                found++;
            } else if (info.name == "source-output-by-application-name:Unrelated saved route") {
                source = info.device;
                matched &= info.device == "physical_input" + suffix || (follow_default && info.device == null);
                found++;
            } else if (preserve_processing && info.name == "sink-input-by-application-name:Processed saved route") {
                processed_sink = info.device;
                matched &= info.device == Sound.EchoCancellation.SINK_NAME || (follow_default && info.device == null);
                found++;
            } else if (preserve_processing && info.name == "source-output-by-application-name:Processed saved route") {
                processed_source = info.device;
                matched &= info.device == Sound.EchoCancellation.SOURCE_NAME || (follow_default && info.device == null);
                found++;
            }
        });
        yield;
        if (found == (preserve_processing ? 4 : 2) && matched) {
            return;
        }
        Timeout.add (25, () => {
            check_routes.callback ();
            return Source.REMOVE;
        });
        yield;
    } while (get_monotonic_time () < deadline);
    error ("Saved routes did not reach devices %s: sink %s, source %s, processed sink %s, processed source %s",
        suffix, sink ?? "default", source ?? "default", processed_sink ?? "default", processed_source ?? "default");
}

Sound.Device other_device (bool input, string suffix = "2") {
    var device = new Sound.Device ("fixture", 42, "fixture") {
        input = input,
        card_active_profile_name = "fixture",
        card_sink_port_name = "fixture",
        card_source_port_name = "fixture",
        sink_name = "physical_output" + suffix,
        source_name = "physical_input" + suffix
    };
    device.profiles.add ("fixture");
    return device;
}

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
    var pulse_loop = new PulseAudio.GLibMainLoop ();
    var context = new PulseAudio.Context (pulse_loop.get_api (), "Sound application test");
    PulseAudio.Stream? playback = null;
    PulseAudio.Stream? capture = null;
    PulseAudio.Stream? ordinary_playback = null;
    PulseAudio.Stream? ordinary_capture = null;
    context.set_state_callback ((c) => {
        if (c.get_state () == PulseAudio.Context.State.READY) {
            var sample = PulseAudio.SampleSpec () {
                format = PulseAudio.SampleFormat.S16NE,
                rate = 48000,
                channels = 2
            };
            playback = new PulseAudio.Stream (c, "Sound application test", sample);
            playback.connect_playback (null, null, PulseAudio.Stream.Flags.START_CORKED);
        }
    });
    uint phase = 0;
    int64 clicked_at = 0;
    bool external_sink = false;
    bool external_source = false;
    bool race_with_aec = false;
    bool optout_external = false;
    context.set_subscribe_callback ((c, event, index) => {
        defaults.begin (c, (object, result) => {
            var names = defaults.end (result);
            if (phase != 70 || names.length != 2) {
                return;
            }
            if (!external_sink && names[0] == "physical_output") {
                external_sink = true;
                context.set_default_sink ("physical_output2", null);
            }
            if (!external_source && names[1] == "physical_input") {
                external_source = true;
                context.set_default_source ("physical_input2", null);
            }
        });
    });
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
            assert (pam.apps.get_n_items () == 0);
            context.connect (null, PulseAudio.Context.Flags.NOAUTOSPAWN);
            phase = 2;
        } else if (phase == 2 && pam.apps.get_n_items () == 1) {
            assert (((Sound.App) pam.apps.get_item (0)).media_name == "Sound application test");
            phase = 20;
            save_routes.begin (pam.context, "2", () => {
                var missing_sink = other_device (false);
                missing_sink.sink_name = "missing_output";
                pam.set_default_device.begin (missing_sink, (object, result) => {
                    pam.set_default_device.end (result);
                    var missing_source = other_device (true);
                    missing_source.source_name = "missing_input";
                    pam.set_default_device.begin (missing_source, (object, result) => {
                        pam.set_default_device.end (result);
                        phase = 30;
                    });
                });
            });
        } else if (phase == 30 && toggle.sensitive) {
            toggle.activate ();
            phase = 3;
        } else if (phase == 3 && !controller.enabled) {
            assert (pam.apps.get_n_items () == 1);
            playback.disconnect ();
            assert (!toggle.active);
            phase = 21;
            check_routes.begin (pam.context, "2", false, false, () => {
                print ("PASS failed default selections and disabling preserve unrelated saved routes\n");
                phase = 40;
            });
        } else if (phase == 40 && toggle.sensitive) {
            toggle.activate ();
            phase = 4;
        } else if (phase == 4 && controller.enabled) {
            var sample = PulseAudio.SampleSpec () {
                format = PulseAudio.SampleFormat.S16NE, rate = 48000, channels = 2
            };
            playback = new PulseAudio.Stream (context, "Sound application test", sample);
            capture = new PulseAudio.Stream (context, "Sound recording test", sample);
            playback.set_write_callback ((stream, bytes) => {
                uint8[] silence = new uint8[bytes];
                stream.write (silence, bytes);
            });
            capture.set_read_callback ((stream, bytes) => {
                void* data;
                size_t length;
                if (stream.peek (out data, out length) == 0) {
                    stream.drop ();
                }
            });
            // ALSA's null PCM has no capture clock. Keep Pulse streams corked
            // while testing their native routing; PipeWire streams run normally.
            var flags = Environment.get_variable ("PULSE_SERVER").has_prefix ("unix:/tmp/vale-sound-pulse-") ?
                PulseAudio.Stream.Flags.START_CORKED : (PulseAudio.Stream.Flags) 0;
            playback.connect_playback (Sound.EchoCancellation.SINK_NAME, null, flags);
            capture.connect_record (Sound.EchoCancellation.SOURCE_NAME, null, flags);
            var ordinary_props = new PulseAudio.Proplist ();
            ordinary_props.sets (PulseAudio.Proplist.PROP_APPLICATION_NAME, "Unprocessed application");
            ordinary_playback = new PulseAudio.Stream (context, "Raw playback", sample, null, ordinary_props);
            ordinary_capture = new PulseAudio.Stream (context, "Raw capture", sample, null, ordinary_props);
            ordinary_playback.connect_playback ("physical_output", null, PulseAudio.Stream.Flags.START_CORKED);
            ordinary_capture.connect_record ("physical_input", null, PulseAudio.Stream.Flags.START_CORKED);
            phase = 24;
        } else if (phase == 24 && playback.get_state () == PulseAudio.Stream.State.READY &&
                   capture.get_state () == PulseAudio.Stream.State.READY &&
                   ordinary_playback.get_state () == PulseAudio.Stream.State.READY &&
                   ordinary_capture.get_state () == PulseAudio.Stream.State.READY) {
            phase = 22;
            save_routes.begin (pam.context, "", () => {
                var missing_card = other_device (false);
                missing_card.card_active_profile_name = "old-profile";
                pam.set_default_device.begin (missing_card, (object, result) => {
                    pam.set_default_device.end (result);
                    pam.set_default_device.begin (other_device (false));
                    pam.set_default_device.begin (other_device (true));
                    phase = 5;
                });
            });
        } else if (phase == 5 && controller.enabled &&
                   controller.source_master == "physical_input2" && controller.sink_master == "physical_output2" &&
                   playback.get_device_name () == Sound.EchoCancellation.SINK_NAME &&
                   capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME &&
                   (ordinary_playback.get_device_name () == "physical_output2" ||
                    ordinary_playback.get_device_name () == Sound.EchoCancellation.SINK_NAME) &&
                   (ordinary_capture.get_device_name () == "physical_input2" ||
                    ordinary_capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME)) {
            // Servers may follow the new default into the owner's filter;
            // either route must reach the newly selected physical master.
            phase = 23;
            defaults.begin (context, (object, result) => {
                var names = defaults.end (result);
                assert (names.length == 2 && names[0] == Sound.EchoCancellation.SINK_NAME &&
                        names[1] == Sound.EchoCancellation.SOURCE_NAME);
                check_routes.begin (pam.context, "2", true, true, () => {
                    assert (capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME);
                    assert (playback.get_device_name () == Sound.EchoCancellation.SINK_NAME);
                    assert (ordinary_playback.get_device_name () == "physical_output2" ||
                            (controller.enabled && controller.sink_master == "physical_output2" &&
                             ordinary_playback.get_device_name () == Sound.EchoCancellation.SINK_NAME));
                    assert (ordinary_capture.get_device_name () == "physical_input2" ||
                            (controller.enabled && controller.source_master == "physical_input2" &&
                             ordinary_capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME));
                    print ("PASS failed selection releases the guard; valid selection preserves processing\n");
                    phase = 80;
                    context.move_sink_input_by_name (playback.get_index (), "physical_output2");
                    context.move_source_output_by_name (capture.get_index (), "physical_input2");
                });
            });
        } else if (phase == 80 && playback.get_device_name () == "physical_output2" &&
                   capture.get_device_name () == "physical_input2") {
            phase = 81;
            if (optout_external) {
                context.set_default_sink ("physical_output", null);
                context.set_default_source ("physical_input", null);
            } else {
                pam.set_default_device.begin (other_device (false, ""));
                pam.set_default_device.begin (other_device (true, ""));
            }
        } else if (phase == 81 && controller.sink_master == "physical_output" &&
                   controller.source_master == "physical_input" &&
                   (playback.get_device_name () == "physical_output" ||
                    playback.get_device_name () == Sound.EchoCancellation.SINK_NAME) &&
                   (capture.get_device_name () == "physical_input" ||
                    capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME)) {
            print ("PASS explicitly opted-out streams follow subsequent %s selections\n",
                optout_external ? "external" : "Sound");
            phase = 82;
            context.move_sink_input_by_name (playback.get_index (), Sound.EchoCancellation.SINK_NAME);
            context.move_source_output_by_name (capture.get_index (), Sound.EchoCancellation.SOURCE_NAME);
        } else if (phase == 82 && playback.get_device_name () == Sound.EchoCancellation.SINK_NAME &&
                   capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME) {
            phase = 83;
            pam.set_default_device.begin (other_device (false));
            pam.set_default_device.begin (other_device (true));
        } else if (phase == 83 && controller.sink_master == "physical_output2" &&
                   controller.source_master == "physical_input2" &&
                   playback.get_device_name () == Sound.EchoCancellation.SINK_NAME &&
                   capture.get_device_name () == Sound.EchoCancellation.SOURCE_NAME) {
            if (!optout_external) {
                optout_external = true;
                phase = 80;
                context.move_sink_input_by_name (playback.get_index (), "physical_output2");
                context.move_source_output_by_name (capture.get_index (), "physical_input2");
            } else {
                phase = 62;
            }
        } else if (phase == 60 && toggle.sensitive) {
            toggle.activate ();
            phase = 6;
        } else if ((phase == 62 && controller.enabled) || (phase == 6 && !controller.enabled)) {
            race_with_aec = controller.enabled;
            external_sink = external_source = false;
            phase = 70;
            subscribe.begin (context, (object, result) => {
                subscribe.end (result);
                pam.set_default_device.begin (other_device (false, ""));
                pam.set_default_device.begin (other_device (true, ""));
                clicked_at = get_monotonic_time ();
            });
        } else if (phase == 70 && external_sink && external_source &&
                   get_monotonic_time () - clicked_at > 1000000 && controller.enabled == race_with_aec) {
            if (race_with_aec && (controller.source_master != "physical_input2" ||
                                 controller.sink_master != "physical_output2")) {
                return Source.CONTINUE;
            }
            // The owner and application connections receive moved events
            // separately. Wait for both before inspecting saved routes.
            if (playback.get_device_name () != (race_with_aec ? Sound.EchoCancellation.SINK_NAME : "physical_output2") ||
                capture.get_device_name () != (race_with_aec ? Sound.EchoCancellation.SOURCE_NAME : "physical_input2") ||
                (ordinary_playback.get_device_name () != "physical_output2" &&
                 (!race_with_aec || ordinary_playback.get_device_name () != Sound.EchoCancellation.SINK_NAME)) ||
                (ordinary_capture.get_device_name () != "physical_input2" &&
                 (!race_with_aec || ordinary_capture.get_device_name () != Sound.EchoCancellation.SOURCE_NAME))) {
                return Source.CONTINUE;
            }
            phase = 71;
            defaults.begin (context, (object, result) => {
                var names = defaults.end (result);
                assert (names.length == 2 && names[0] ==
                        (race_with_aec ? Sound.EchoCancellation.SINK_NAME : "physical_output2") &&
                        names[1] == (race_with_aec ? Sound.EchoCancellation.SOURCE_NAME : "physical_input2"));
                // A route may omit its device when it follows this verified default.
                check_routes.begin (pam.context, "2", true, race_with_aec, () => {
                    print ("PASS competing selections retain current routes and processing %s\n", race_with_aec.to_string ());
                    if (race_with_aec) {
                        phase = 60;
                    } else {
                        loop.quit ();
                    }
                });
            });
        }

        return Source.CONTINUE;
    });
    // Four module transitions and a paired device selection each have bounded
    // backend operations; the complete sequence needs more than one deadline.
    Timeout.add_seconds (60, () => {
        var controller = pam.echo_cancellation;
        stderr.printf ("Streams at timeout: playback=%s capture=%s ordinary playback=%s capture=%s\n",
            playback == null ? "none" : playback.get_device_name (),
            capture == null ? "none" : capture.get_device_name (),
            ordinary_playback == null ? "none" : ordinary_playback.get_device_name (),
            ordinary_capture == null ? "none" : ordinary_capture.get_device_name ());
        error ("InputPanel timeout: phase %u, enabled %s, busy %s, available %s, error %s, switch %s, preference %s",
            phase, controller.enabled.to_string (), controller.busy.to_string (), controller.available.to_string (),
            controller.error ?? "none", toggle.active.to_string (),
            new Settings ("io.elementary.settings-daemon.audio").get_boolean ("echo-cancellation").to_string ());
    });
    loop.run ();
    playback.disconnect ();
    capture.disconnect ();
    ordinary_playback.disconnect ();
    ordinary_capture.disconnect ();
    context.disconnect ();
    window.destroy ();
    return 0;
}
