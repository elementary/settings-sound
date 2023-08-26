/*
* SPDX-License-Identifier: LGPL-3.0-or-later
* SPDX-FileCopyrightText: 2023 elementary, Inc. (https://elementary.io)
*
* Authored by: Leonhard Kargl <leo.kargl@proton.me>
*/

public class Sound.ApplicationsPanel : Gtk.Box {
    construct {
        var pulse_audio_manager = PulseAudioManager.get_default ();

        var placeholder = new Granite.Widgets.AlertView (
            _("No applications currently emittings sounds"),
            _("Applications emitting sounds will automatically appear here"),
            "dialog-information"
        );
        placeholder.show_all ();

        var list_box = new Gtk.ListBox () {
            selection_mode = NONE,
        };
        list_box.bind_model (pulse_audio_manager.apps, widget_create_func);
        list_box.set_placeholder (placeholder);

        var scrolled_window = new Gtk.ScrolledWindow (null, null) {
            child = list_box,
            vexpand = true
        };

        var frame = new Gtk.Frame (null) {
            child = scrolled_window
        };

        var reset_button = new Gtk.Button.with_label (_("Reset all apps to default"));

        orientation = VERTICAL;
        spacing = 12;
        add (frame);
        add (reset_button);

        reset_button.clicked.connect (() => {
            for (int i = 0; i < pulse_audio_manager.apps.get_n_items (); i++) {
                pulse_audio_manager.change_application_volume ((App) pulse_audio_manager.apps.get_item (i), 1);
            }
        });
    }

    private Gtk.Widget widget_create_func (Object item) {
        var app = (App) item;
        var app_row = new AppRow ();
        app_row.bind_app (app);
        app_row.show_all ();
        return app_row;
    }
}
