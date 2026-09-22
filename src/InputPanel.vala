/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2016-2023 elementary, Inc. (https://elementary.io)
 *
 * Authored by: Corentin Noël <corentin@elementary.io>
 */

public class Sound.InputPanel : Gtk.Box {
    private Device? default_device = null;
    private Gtk.LevelBar level_bar;
    private Gtk.ListBox devices_listbox;
    private Gtk.Scale volume_scale;
    private Gtk.Switch volume_switch;
    private InputDeviceMonitor device_monitor;
    private uint monitor_timeout_id = 0;
    private unowned PulseAudioManager pam;

    construct {
        margin_bottom = 12;

        var no_device_grid = new Granite.Placeholder (
            _("No Connected Audio Devices Detected")
        ) {
            description = _("Check that all cables are securely attached and audio input devices are powered on."),
            icon = new ThemedIcon ("audio-input-microphone-symbolic")
        };

        devices_listbox = new Gtk.ListBox () {
            activate_on_single_click = true,
            vexpand = true
        };
        devices_listbox.set_placeholder (no_device_grid);
        devices_listbox.add_css_class (Granite.STYLE_CLASS_RICH_LIST);

        devices_listbox.row_activated.connect ((row) => {
            pam.set_default_device.begin (((Sound.DeviceRow) row).device);
        });

        var scrolled = new Gtk.ScrolledWindow () {
            child = devices_listbox
        };

        var devices_frame = new Gtk.Frame (null) {
            child = scrolled
        };

        var volume_label = new Granite.HeaderLabel (_("Input Volume"));

        volume_scale = new Gtk.Scale.with_range (Gtk.Orientation.HORIZONTAL, 0, 100, 5) {
            draw_value = false,
            hexpand = true,
            margin_top = 3
        };

        volume_scale.add_mark (10, Gtk.PositionType.BOTTOM, _("Unamplified"));
        volume_scale.add_mark (80, Gtk.PositionType.BOTTOM, _("100%"));

        volume_switch = new Gtk.Switch () {
            valign = START
        };

        level_bar = new Gtk.LevelBar.for_interval (0.0, 1.0);
        level_bar.add_css_class ("inverted");

        level_bar.add_offset_value ("low", 0.8);
        level_bar.add_offset_value ("high", 0.95);
        level_bar.add_offset_value ("full", 1.0);

        var volume_grid = new Gtk.Grid () {
            column_spacing = 12,
            row_spacing = 3
        };
        volume_grid.attach (volume_label, 0, 0);
        volume_grid.attach (level_bar, 0, 1);
        volume_grid.attach (volume_scale, 0, 2);
        volume_grid.attach (volume_switch, 1, 1, 1, 2);

        orientation = VERTICAL;
        spacing = 18;
        append (devices_frame);
        append (volume_grid);

        device_monitor = new InputDeviceMonitor ();
        device_monitor.update_fraction.connect ((fraction) => {
            if (fraction >= level_bar.value) {
                level_bar.value = fraction;
                return;
            }

            monitor_timeout_id = Timeout.add (1, () => {
                level_bar.value = level_bar.value * 0.95;
                monitor_timeout_id = 0;
                return Source.REMOVE;
            });
        });

        pam = PulseAudioManager.get_default ();
        pam.new_device.connect (add_device);
        pam.notify["default-input"].connect (() => {
            default_changed ();
        });

        connect_signals ();
    }

    public void set_visibility (bool is_visible) {
        if (is_visible) {
            device_monitor.start_record ();
        } else {
            device_monitor.stop_record ();
        }
    }

    private void disconnect_signals () {
        volume_switch.notify["active"].disconnect (volume_switch_changed);
        volume_scale.value_changed.disconnect (volume_scale_value_changed);
    }

    private void connect_signals () {
        volume_switch.notify["active"].connect (volume_switch_changed);
        volume_scale.value_changed.connect (volume_scale_value_changed);
    }

    private void volume_scale_value_changed () {
        disconnect_signals ();
        pam.change_device_volume (default_device, volume_scale.get_value ());
        connect_signals ();
    }

    private void volume_switch_changed () {
        disconnect_signals ();
        pam.change_device_mute (default_device, !volume_switch.active);
        connect_signals ();
    }

    private void default_changed () {
        disconnect_signals ();
        lock (default_device) {
            if (default_device != null) {
                default_device.notify.disconnect (device_notify);
            }

            default_device = pam.default_input;
            if (default_device != null) {
                device_monitor.set_device (default_device);
                if (volume_switch.active == default_device.is_muted) {
                    volume_switch.activate ();
                }
                volume_scale.set_value (default_device.volume);
                default_device.notify.connect (device_notify);
            }
        }

        connect_signals ();
    }

    private void device_notify (ParamSpec pspec) {
        disconnect_signals ();
        switch (pspec.get_name ()) {
            case "is-muted":
                if (volume_switch.active == default_device.is_muted) {
                    volume_switch.activate ();
                }

                volume_scale.sensitive = !default_device.is_muted;
                break;
            case "volume":
                volume_scale.set_value (default_device.volume);
                break;
        }

        connect_signals ();
    }

    private void add_device (Device device) {
        if (!device.input) {
            return;
        }

        var device_row = new DeviceRow (device);
        Gtk.ListBoxRow? row = devices_listbox.get_row_at_index (0);
        if (row != null) {
            device_row.link_to_row ((DeviceRow) row);
        }

        devices_listbox.append (device_row);
        device_row.set_as_default.connect (() => {
            pam.set_default_device.begin (device);
        });

        device.removed.connect (() => devices_listbox.remove (device_row));
    }
}
