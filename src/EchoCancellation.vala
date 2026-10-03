/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2026 elementary, Inc. (https://elementary.io)
 */

public class Sound.EchoCancellation : Object {
    public const string SOURCE_NAME = "elementary_echo_cancel_source";
    public const string SINK_NAME = "elementary_echo_cancel_sink";

    public struct Status {
        public bool enabled;
        public bool available;
        public bool busy;
        public string error;
        public string source_master;
        public string sink_master;
    }

    [DBus (name = "io.elementary.settings_daemon.Audio")]
    private interface Audio : DBusProxy {
        public abstract async Status get_status () throws DBusError, IOError;
        public signal void state_changed ();
    }

    public bool requested { get; set; }
    public bool enabled { get; private set; }
    public bool available { get; private set; }
    public bool busy { get; private set; }
    public string? error { get; private set; }
    public string? source_master { get; private set; }
    public string? sink_master { get; private set; }

    private Settings? settings;
    private Audio? audio;
    private uint owner_generation;

    construct {
        var schema = SettingsSchemaSource.get_default ().lookup ("io.elementary.settings-daemon.audio", true);
        if (schema == null) {
            error = _("The settings audio service is unavailable.");
            return;
        }
        settings = new Settings.full (schema, null, null);
        settings.bind ("echo-cancellation", this, "requested", SettingsBindFlags.DEFAULT);
        Bus.watch_name (SESSION, "io.elementary.settings-daemon", NONE, (connection) => {
            var generation = ++owner_generation;
            connection.get_proxy.begin<Audio> ("io.elementary.settings-daemon", "/io/elementary/settings_daemon", NONE,
                null, (obj, res) => {
                    try {
                        var proxy = connection.get_proxy.end<Audio> (res);
                        if (generation != owner_generation) {
                            return;
                        }
                        audio = proxy;
                        audio.state_changed.connect (() => refresh.begin ());
                        refresh.begin ();
                    } catch (Error e) {
                        if (generation == owner_generation) {
                            error = e.message;
                        }
                    }
                });
        }, () => {
            owner_generation++;
            audio = null;
            source_master = sink_master = null;
            enabled = available = busy = false;
            error = _("The settings audio service is unavailable.");
        });
    }

    public async void refresh () {
        var generation = owner_generation;
        var service = audio;
        if (service == null) {
            return;
        }
        try {
            var status = yield service.get_status ();
            if (generation != owner_generation || service != audio) {
                return;
            }
            enabled = status.enabled;
            available = status.available;
            busy = status.busy;
            error = status.error;
            source_master = status.source_master == "" ? null : status.source_master;
            sink_master = status.sink_master == "" ? null : status.sink_master;
        } catch (Error e) {
            if (generation != owner_generation || service != audio) {
                return;
            }
            available = busy = false;
            error = e.message;
        }
    }

    public void request (bool enable) {
        if (settings != null) {
            requested = enable;
        }
    }

    public string? resolve_source (string? name) {
        return name == SOURCE_NAME ? source_master : name;
    }

    public string? resolve_sink (string? name) {
        return name == SINK_NAME ? sink_master : name;
    }
}
