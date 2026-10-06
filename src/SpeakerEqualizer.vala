/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2026 elementary, Inc. (https://elementary.io)
 */

public class Sound.SpeakerEqualizer : Object {
    public struct Status {
        public bool available;
        public bool busy;
        public bool applied;
        public string error;
        public string settings_path;
        public string node;
        public string route;
        public double[] frequencies;
        public string[] types;
        public double[] defaults;
        public double[] minimum;
        public double[] maximum;
    }

    [DBus (name = "io.elementary.settings_daemon.Audio")]
    private interface Audio : DBusProxy {
        public abstract async Status get_equalizer_status () throws DBusError, IOError;
        public signal void equalizer_changed ();
    }

    public SpeakerEqualizer () { clear (); }

    public signal void changed ();
    public Status status;
    public bool requested {
        get {
            if (settings == null) {
                return false;
            }
            var saved = settings.get_user_value ("enabled");
            return saved != null ? saved.get_boolean () :
                status.defaults.length == 5 && settings.get_boolean ("enabled");
        }
    }
    public double[] get_gains () {
        if (settings == null) {
            return new double[0];
        }
        var value = settings.get_user_value ("gains");
        if (value == null) {
            return status.defaults.length == 5 ? status.defaults.copy () : new double[5];
        }
        if (value.n_children () != 5) {
            return new double[0];
        }
        var values = new double[5];
        for (int i = 0; i < 5; i++) {
            values[i] = value.get_child_value (i).get_double ();
            if (!values[i].is_finite () || values[i] < status.minimum[i] || values[i] > status.maximum[i]) {
                return new double[0];
            }
        }
        return values;
    }

    private Audio? audio;
    private Settings? settings;
    private uint watch;
    private uint generation;
    private bool reading;
    private bool pending;

    public void start () {
        if (watch != 0) return;
        clear ();
        watch = Bus.watch_name (SESSION, "io.elementary.settings-daemon", NONE, (connection) => {
            uint request = ++generation;
            connection.get_proxy.begin<Audio> ("io.elementary.settings-daemon", "/io/elementary/settings_daemon", NONE,
                null, (obj, res) => {
                    try {
                        var proxy = connection.get_proxy.end<Audio> (res);
                        if (request != generation) return;
                        proxy.g_default_timeout = 2000;
                        audio = proxy;
                        audio.equalizer_changed.connect (refresh);
                        refresh ();
                    } catch (Error e) {
                        if (request == generation) clear ();
                    }
                });
        }, () => {
            generation++;
            if (audio != null) audio.equalizer_changed.disconnect (refresh);
            audio = null;
            clear ();
        });
    }

    public void stop () {
        generation++;
        if (watch != 0) Bus.unwatch_name (watch);
        watch = 0;
        if (audio != null) audio.equalizer_changed.disconnect (refresh);
        audio = null;
        clear ();
    }

    private void clear () {
        if (settings != null) settings.changed.disconnect (preferences_changed);
        settings = null;
        status = { false, false, false, _("Speaker equalization is unavailable."), "", "", "",
            new double[0], new string[0], new double[0], new double[0], new double[0] };
        changed ();
    }

    private void preferences_changed () { changed (); }

    private void refresh () {
        pending = true;
        if (!reading) read_status.begin ();
    }

    private async void read_status () {
        var service = audio;
        if (service == null) return;
        reading = true;
        pending = false;
        uint request = generation;
        try {
            var result = yield service.get_equalizer_status ();
            if (request == generation && service == audio) {
                var schema = SettingsSchemaSource.get_default ().lookup (
                    "io.elementary.settings-daemon.audio.equalizer", true);
                if (schema == null || !valid_status (result)) {
                    clear ();
                } else {
                    if (settings == null || status.settings_path != result.settings_path) {
                        if (settings != null) settings.changed.disconnect (preferences_changed);
                        settings = new Settings.full (schema, null, result.settings_path);
                        settings.delay ();
                        settings.changed.connect (preferences_changed);
                    }
                    status = result;
                    changed ();
                }
            }
        } catch (Error e) {
            if (request == generation && service == audio) clear ();
        }
        reading = false;
        if (pending && audio != null) read_status.begin ();
    }

    private static bool valid_status (Status value) {
        const string PREFIX = "/io/elementary/settings-daemon/audio/equalizer/";
        if (!value.settings_path.has_prefix (PREFIX) || value.settings_path.length != PREFIX.length + 65 ||
            !value.settings_path.has_suffix ("/") || value.frequencies.length != 5 || value.types.length != 5 ||
            (value.defaults.length != 0 && value.defaults.length != 5) || value.minimum.length != 5 || value.maximum.length != 5) return false;
        foreach (char digit in value.settings_path.substring (PREFIX.length, 64).to_utf8 ()) {
            if (digit != 0 && !digit.isxdigit ()) return false;
        }
        for (int i = 0; i < 5; i++) {
            if ((value.types[i] != "low-shelf" && value.types[i] != "peak" && value.types[i] != "high-shelf") ||
                !value.frequencies[i].is_finite () || value.frequencies[i] < 20 || value.frequencies[i] > 20000 ||
                !value.minimum[i].is_finite () || !value.maximum[i].is_finite () ||
                value.minimum[i] < -24 || value.minimum[i] > 0 || value.maximum[i] < 0 || value.maximum[i] > 12 ||
                (value.defaults.length == 5 && (!value.defaults[i].is_finite () ||
                    value.defaults[i] < value.minimum[i] || value.defaults[i] > value.maximum[i]))) return false;
        }
        return true;
    }

    public void enable (bool enabled) {
        if (settings == null || (enabled && !status.available)) return;
        settings.set_boolean ("enabled", enabled);
        settings.apply ();
    }

    public void reset () {
        if (settings == null || !status.available) {
            return;
        }
        set_gains (status.defaults.length == 5 ? status.defaults : new double[5]);
    }

    public void set_band (int band, double gain) {
        if (settings == null || !status.available || band < 0 || band >= 5 || !gain.is_finite () ||
            gain < status.minimum[band] || gain > status.maximum[band]) return;
        var values = get_gains ();
        if (values.length != 5) return;
        values[band] = gain;
        set_gains (values);
    }

    private void set_gains (double[] values) {
        var builder = new VariantBuilder (new VariantType ("ad"));
        foreach (double gain in values) builder.add ("d", gain);
        settings.set_value ("gains", builder.end ());
        settings.apply ();
    }
}
