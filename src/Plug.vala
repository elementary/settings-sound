/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2016-2023 elementary, Inc. (https://elementary.io)
 *
 * Authored by: Corentin Noël <corentin@elementary.io>
 */

public class Sound.Plug : Switchboard.Plug {
    private Gtk.Box box;
    private Gtk.Stack stack;
    private InputPanel input_panel;

    public Plug () {
        GLib.Intl.bindtextdomain (GETTEXT_PACKAGE, LOCALEDIR);
        GLib.Intl.bind_textdomain_codeset (GETTEXT_PACKAGE, "UTF-8");

        var settings = new Gee.TreeMap<string, string?> (null, null);
        settings.set ("sound", null);
        settings.set ("sound/applications", "applications");
        settings.set ("sound/input", "input");
        settings.set ("sound/output", "output");
        Object (category: Category.HARDWARE,
                code_name: "io.elementary.settings.sound",
                display_name: _("Sound"),
                description: _("Change sound and microphone volume"),
                icon: "multimedia-volume-control",
                supported_settings: settings);
    }

    public override Gtk.Widget get_widget () {
        if (box == null) {
            var output_panel = new OutputPanel ();
            input_panel = new InputPanel ();
            var applications_panel = new ApplicationsPanel ();

            stack = new Gtk.Stack () {
                hexpand = true,
                vexpand = true,
                margin_start = 12,
                margin_end = 12,
                margin_bottom = 12
            };
            stack.add_titled (output_panel, "output", _("Output"));
            stack.add_titled (input_panel, "input", _("Input"));
            stack.add_titled (applications_panel, "applications", _("Applications"));

            var stack_switcher = new Gtk.StackSwitcher () {
                halign = Gtk.Align.CENTER,
                stack = stack
            };
            ((Gtk.BoxLayout) stack_switcher.layout_manager).homogeneous = true;

            var clamp = new Adw.Clamp () {
                child = stack
            };

            var headerbar = new Adw.HeaderBar () {
                title_widget = stack_switcher
            };
            headerbar.add_css_class (Granite.STYLE_CLASS_FLAT);

            box = new Gtk.Box (VERTICAL, 0);
            box.append (headerbar);
            box.append (clamp);

            var pam = PulseAudioManager.get_default ();
            pam.start ();

            stack.notify["visible-child"].connect (() => {
                input_panel.set_visibility (stack.visible_child == input_panel);
            });
        }

        return box;
    }

    public override void shown () {
        box.show ();
        if (stack.visible_child == input_panel) {
            input_panel.set_visibility (true);
        }
    }

    public override void hidden () {
    }

    public override void search_callback (string location) {
        stack.set_visible_child_name (location);
    }

    // 'search' returns results like ("Keyboard → Behavior → Duration", "keyboard<sep>behavior")
    public override async Gee.TreeMap<string, string> search (string search) {
        var search_results = new Gee.TreeMap<string, string> ();
        search_results.set ("%s → %s".printf (display_name, _("Output")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Device")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Event Alerts")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Port")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Volume")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Balance")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Screen Reader")), "output");
        search_results.set ("%s → %s → %s".printf (display_name, _("Output"), _("Test Speakers")), "output");
        search_results.set ("%s → %s".printf (display_name, _("Input")), "input");
        search_results.set ("%s → %s → %s".printf (display_name, _("Input"), _("Device")), "input");
        search_results.set ("%s → %s → %s".printf (display_name, _("Input"), _("Port")), "input");
        search_results.set ("%s → %s → %s".printf (display_name, _("Input"), _("Volume")), "input");
        search_results.set ("%s → %s → %s".printf (display_name, _("Input"), _("Enable")), "input");
        search_results.set ("%s → %s".printf (display_name, _("Applications")), "applications");
        return search_results;
    }
}


public Switchboard.Plug get_plug (Module module) {
    debug ("Activating Sound plug");
    var plug = new Sound.Plug ();
    return plug;
}
