/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2026 elementary, Inc. (https://elementary.io)
 */

public class Sound.SpeakerEqualizerPanel : Gtk.Box {
    private SpeakerEqualizer equalizer = new SpeakerEqualizer ();
    private Gtk.Switch enabled;
    private Gtk.Button reset;
    private Gtk.Label feedback;
    private Gtk.Grid bands;
    private Gtk.Scale[] sliders = {};
    private Gtk.Label[] labels = {};
    private Gtk.Label[] values = {};
    private Device? device;
    private bool updating;

    construct {
        orientation = VERTICAL;
        spacing = 12;
        var title = new Granite.HeaderLabel (_("Equalizer")) { hexpand = true };
        enabled = new Gtk.Switch () { valign = CENTER };
        var header = new Gtk.Box (HORIZONTAL, 12);
        header.append (title);
        header.append (enabled);
        reset = new Gtk.Button.with_label (_("Reset")) { halign = END };
        reset.tooltip_text = _("Restore recommended equalizer settings");
        bands = new Gtk.Grid () { row_spacing = 6, column_spacing = 12 };
        string[] band_names = { _("Bass"), _("Low mids"), _("Mids"), _("Air"), _("Upper balance") };
        for (int i = 0; i < 5; i++) {
            int band = i;
            var label = new Gtk.Label (band_names[i]) { xalign = 0 };
            var slider = new Gtk.Scale.with_range (HORIZONTAL, -12, 12, 0.5) { hexpand = true, draw_value = false };
            var value = new Gtk.Label ("") { xalign = 1, width_chars = 8 };
            label.mnemonic_widget = slider;
            bands.attach (label, 0, i);
            bands.attach (slider, 1, i);
            bands.attach (value, 2, i);
            labels += label;
            sliders += slider;
            values += value;
            slider.value_changed.connect (() => {
                if (!updating) equalizer.set_band (band, slider.get_value ());
            });
        }
        feedback = new Gtk.Label ("") { wrap = true, xalign = 0 };
        feedback.add_css_class ("dim-label");
        append (header);
        append (bands);
        append (reset);
        append (feedback);
        enabled.notify["active"].connect (() => { if (!updating) equalizer.enable (enabled.active); });
        reset.clicked.connect (equalizer.reset);
        equalizer.changed.connect (update);
        map.connect (() => equalizer.start ());
        unmap.connect (() => equalizer.stop ());
        update ();
    }

    public override void dispose () {
        set_device (null);
        equalizer.stop ();
        base.dispose ();
    }

    public void set_device (Device? selected) {
        if (device != null) device.notify.disconnect (update);
        device = selected;
        if (device != null) device.notify.connect (update);
        update ();
    }

    private void update () {
        updating = true;
        var status = equalizer.status;
        // Wait for the daemon to retire the old graph before showing controls
        // for the newly selected physical output.
        bool matches = device != null && status.node == device.card_sink_name && status.route == device.port_name;
        enabled.visible = reset.visible = matches;
        if (enabled.active != equalizer.requested) enabled.active = equalizer.requested;
        enabled.sensitive = matches && (status.available || enabled.active);
        reset.sensitive = matches && status.available;
        bands.sensitive = matches && status.available;
        var gains = equalizer.get_gains ();
        bands.visible = matches && gains.length == 5;
        if (bands.visible) {
            for (int i = 0; i < 5; i++) {
                labels[i].tooltip_text = _("%g Hz").printf (status.frequencies[i]);
                sliders[i].set_range (status.minimum[i], status.maximum[i]);
                sliders[i].set_value (gains[i]);
                values[i].label = _("%+.1f dB").printf (gains[i]);
            }
        }
        feedback.label = !matches ? _("Speaker equalization is unavailable for this output.") :
            status.error;
        feedback.visible = feedback.label != "";
        updating = false;
    }
}
