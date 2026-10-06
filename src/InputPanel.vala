/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2016-2023 elementary, Inc. (https://elementary.io)
 *
 * Authored by: Corentin Noël <corentin@elementary.io>
 */

public class Sound.InputPanel : Switchboard.SettingsPage {
    private Device? default_device = null;
    private Gtk.LevelBar level_bar;
    private Gtk.ListBox devices_listbox;
    private Gtk.Scale volume_scale;
    private Gtk.Switch volume_switch;
    private Gtk.Switch echo_switch;
    private Gtk.Label echo_status;
    private ulong echo_switch_handler;
    private EchoCancellation echo_cancellation;
    private InputDeviceMonitor device_monitor;
    private bool monitor_visible;
    private unowned PulseAudioManager pam;

    public InputPanel () {
        Object (
            title: _("Input"),
            icon: new ThemedIcon ("audio-input-microphone")
        );
    }

    construct {
        show_end_title_buttons = true;

        var no_device_grid = new Granite.Placeholder (
            _("No Connected Audio Devices Detected")
        ) {
            description = _("Check that all cables are securely attached and audio input devices are powered on."),
            icon = new ThemedIcon ("audio-input-microphone-symbolic")
        };

        devices_listbox = new Gtk.ListBox () {
            activate_on_single_click = true
        };
        devices_listbox.set_placeholder (no_device_grid);
        devices_listbox.add_css_class (Granite.STYLE_CLASS_RICH_LIST);

        devices_listbox.row_activated.connect ((row) => {
            pam.set_default_device.begin (((Sound.DeviceRow) row).device);
        });

        var devices_frame = new Gtk.Frame (null) {
            child = devices_listbox
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

        echo_switch = new Gtk.Switch () {
            valign = START
        };
        echo_switch.state_set.connect (() => {
            return true;
        });
        echo_switch_handler = echo_switch.notify["active"].connect (() => {
            echo_cancellation.request (echo_switch.active);
        });

        var echo_description = new Gtk.Label (
            _("Reduce background noise and speaker echo in new applications using the default microphone.")
        ) {
            wrap = true,
            xalign = 0,
            hexpand = true
        };
        echo_description.add_css_class (Granite.STYLE_CLASS_DIM_LABEL);

        echo_status = new Gtk.Label (null) {
            wrap = true,
            xalign = 0
        };
        echo_status.add_css_class (Granite.STYLE_CLASS_DIM_LABEL);

        var echo_grid = new Gtk.Grid () {
            column_spacing = 12,
            row_spacing = 3
        };
        echo_grid.attach (new Granite.HeaderLabel (_("Noise Cancellation")), 0, 0);
        echo_grid.attach (echo_description, 0, 1);
        echo_grid.attach (echo_status, 0, 2);
        echo_grid.attach (echo_switch, 1, 0, 1, 2);

        var content_box = new Gtk.Box (VERTICAL, 18);
        content_box.append (devices_frame);
        content_box.append (volume_grid);
        content_box.append (echo_grid);
        child = content_box;

        device_monitor = new InputDeviceMonitor ();
        device_monitor.update_fraction.connect ((fraction) => {
            level_bar.value = fraction;
        });

        pam = PulseAudioManager.get_default ();
        echo_cancellation = pam.echo_cancellation;
        echo_cancellation.notify.connect (echo_status_changed);
        echo_status_changed ();
        pam.new_device.connect (add_device);
        pam.notify["default-input"].connect (() => {
            default_changed ();
        });

        connect_signals ();
    }

    private void echo_status_changed () {
        SignalHandler.block (echo_switch, echo_switch_handler);
        echo_switch.sensitive = !echo_cancellation.busy &&
            (echo_cancellation.available || echo_cancellation.enabled || echo_cancellation.requested);
        echo_switch.state = echo_cancellation.enabled;
        // Setting active even to its current value cancels GTK's animation.
        if (echo_switch.active != echo_cancellation.requested) {
            echo_switch.active = echo_cancellation.requested;
        }
        SignalHandler.unblock (echo_switch, echo_switch_handler);
        echo_status.label = echo_cancellation.error != null ? echo_cancellation.error : "";
        echo_status.visible = echo_status.label != "";
    }

    public void set_visibility (bool is_visible) {
        monitor_visible = is_visible;
        if (is_visible && default_device != null) {
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
            volume_switch.sensitive = default_device != null;
            volume_scale.sensitive = default_device != null && !default_device.is_muted;
            if (default_device == null) {
                device_monitor.stop_record ();
            }
            if (default_device != null) {
                device_monitor.set_device (default_device);
                if (monitor_visible) {
                    device_monitor.start_record ();
                }
                if (volume_switch.active == default_device.is_muted) {
                    volume_switch.active = !default_device.is_muted;
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
                    volume_switch.active = !default_device.is_muted;
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
