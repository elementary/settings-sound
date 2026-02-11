/*
* SPDX-License-Identifier: LGPL-3.0-or-later
* SPDX-FileCopyrightText: 2023 elementary, Inc. (https://elementary.io)
*
* Authored by: Leonhard Kargl <leo.kargl@proton.me>
*/

public class Sound.AppRow : Gtk.Grid {
    private App? app;
    private Gtk.Label app_name_label;
    private Gtk.Label media_name_label;
    private Gtk.Image image;
    private Gtk.Button icon_button;
    private Gtk.Scale volume_scale;
    private Gtk.Switch mute_switch;

    construct {
        image = new Gtk.Image () {
            icon_size = LARGE
        };

        app_name_label = new Gtk.Label ("") {
            ellipsize = END,
            xalign = 0
        };
        app_name_label.add_css_class (Granite.STYLE_CLASS_H3_LABEL);

        media_name_label = new Gtk.Label ("") {
            ellipsize = END,
            xalign = 0
        };
        media_name_label.add_css_class (Granite.STYLE_CLASS_DIM_LABEL);
        media_name_label.add_css_class (Granite.STYLE_CLASS_SMALL_LABEL);

        var label_box = new Gtk.Box (HORIZONTAL, 6);
        label_box.append (app_name_label);
        label_box.append (media_name_label);

        icon_button = new Gtk.Button.from_icon_name ("audio-volume-muted");

        volume_scale = new Gtk.Scale.with_range (HORIZONTAL, 0, 1, 0.01) {
            hexpand = true
        };

        mute_switch = new Gtk.Switch () {
            valign = CENTER
        };

        hexpand = true;
        column_spacing = 6;

        attach (image, 0, 0, 1, 2);
        attach (label_box, 1, 0, 2);
        attach (icon_button, 1, 1);
        attach (volume_scale, 2, 1);
        attach (mute_switch, 3, 0, 1, 2);

        volume_scale.change_value.connect ((type, new_value) => {
            if (app != null) {
                PulseAudioManager.get_default ().change_application_volume (app, new_value.clamp (0, 1));
            }

            return true;
        });

        icon_button.clicked.connect (() => toggle_mute_application ());

        mute_switch.state_set.connect ((state) => {
            toggle_mute_application (!state);
            return true;
        });
    }

    private void toggle_mute_application (bool? custom = null) {
        if (app == null) {
            return;
        }

        PulseAudioManager.get_default ().mute_application (app, custom != null ? custom : !app.muted);
    }

    private void update () {
        media_name_label.label = media_name_label.tooltip_text = app.media_name;
        volume_scale.set_value (app.volume);
        mute_switch.state = !app.muted;
        mute_switch.set_active (!app.muted);
        volume_scale.sensitive = !app.muted;

        if (app.muted) {
            icon_button.icon_name = "audio-volume-muted";
        } else if (volume_scale.get_value () < 0.33) {
            icon_button.icon_name = "audio-volume-low";
        } else if (volume_scale.get_value () > 0.66) {
            icon_button.icon_name = "audio-volume-high";
        } else {
            icon_button.icon_name = "audio-volume-medium";
        }

        if (app.muted) {
            icon_button.tooltip_text = _("Unmute");
        } else {
            icon_button.tooltip_text = _("Mute");
        }
    }

    public void bind_app (App app) {
        this.app = app;

        app_name_label.label = app.display_name;
        image.set_from_gicon (app.icon);

        app.changed.connect (update);
        app.notify["hidden"].connect (() => {
            visible = app.hidden;
        });

        visible = app.hidden;

        volume_scale.set_value (app.volume);
    }

    public void unbind_app () {
        app.changed.disconnect (update);
    }
}
