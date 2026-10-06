/*
* SPDX-License-Identifier: LGPL-3.0-or-later
* SPDX-FileCopyrightText: 2023 elementary, Inc. (https://elementary.io)
*
* Authored by: Leonhard Kargl <leo.kargl@proton.me>
*/

public class Sound.ApplicationsPanel : Switchboard.SettingsPage {
    public ApplicationsPanel () {
        Object (
            title: _("Applications"),
            icon: new ThemedIcon ("preferences-desktop-apps")
        );
    }

    construct {
        show_end_title_buttons = true;
        var pulse_audio_manager = PulseAudioManager.get_default ();

        var placeholder = new Granite.Placeholder (_("No applications currently emitting sounds")) {
            description = _("Applications emitting sounds will automatically appear here")
        };

        var list_box = new Gtk.ListBox () {
            selection_mode = NONE,
        };
        list_box.bind_model (pulse_audio_manager.apps, widget_create_func);
        list_box.set_placeholder (placeholder);
        list_box.add_css_class (Granite.STYLE_CLASS_RICH_LIST);

        var frame = new Gtk.Frame (null) {
            child = list_box
        };

        var reset_button = new Gtk.Button.with_label (_("Reset all apps to default")) {
            halign = END
        };

        var content_box = new Gtk.Box (VERTICAL, 12);
        content_box.append (frame);
        content_box.append (reset_button);
        child = content_box;

        // TODO: Reset also non active applications
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
        return app_row;
    }
}
