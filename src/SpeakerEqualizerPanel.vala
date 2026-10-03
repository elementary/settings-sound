/*
 * SPDX-License-Identifier: LGPL-2.0-or-later
 * SPDX-FileCopyrightText: 2026 elementary, Inc. (https://elementary.io)
 */

public class Sound.SpeakerEqualizerPanel : Gtk.Box {
    private SpeakerEqualizer equalizer = new SpeakerEqualizer ();
    private Gtk.Switch enabled;
    private Gtk.DropDown presets;
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
        var title = new Granite.HeaderLabel (_("Speaker Equalizer")) { hexpand = true };
        enabled = new Gtk.Switch () { valign = CENTER };
        var header = new Gtk.Box (HORIZONTAL, 12);
        header.append (title);
        header.append (enabled);
        presets = new Gtk.DropDown.from_strings ({ _("Device Default"), _("Flat"), _("Custom") }) { hexpand = true };
        reset = new Gtk.Button.with_label (_("Reset"));
        reset.tooltip_text = _("Restore the device’s default equalizer settings");
        var choices = new Gtk.Box (HORIZONTAL, 12);
        choices.append (presets);
        choices.append (reset);
        bands = new Gtk.Grid () { row_spacing = 6, column_spacing = 12 };
        for (int i = 0; i < 5; i++) {
            int band = i;
            var label = new Gtk.Label ("") { xalign = 0 };
            var slider = new Gtk.Scale.with_range (HORIZONTAL, -24, 12, 0.5) { hexpand = true, draw_value = false };
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
        append (choices);
        append (bands);
        append (feedback);
        enabled.notify["active"].connect (() => { if (!updating) equalizer.enable (enabled.active); });
        presets.notify["selected"].connect (() => {
            if (!updating && presets.selected < 3)
                equalizer.choose_preset (new string[] { "device-default", "flat", "custom" }[presets.selected]);
        });
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
        bool matches = device != null && status.node == device.card_sink_name && status.route == device.port_name;
        if (enabled.active != equalizer.requested) enabled.active = equalizer.requested;
        enabled.sensitive = matches && (status.available || enabled.active);
        presets.sensitive = reset.sensitive = matches && status.available;
        bands.sensitive = matches && status.available && enabled.active;
        presets.selected = equalizer.preset == "flat" ? 1 : equalizer.preset == "custom" ? 2 : 0;
        var gains = equalizer.get_gains ();
        bands.visible = matches && gains.length == 5;
        if (bands.visible) {
            for (int i = 0; i < 5; i++) {
                string kind = status.types[i] == "low-shelf" ? _("Low Shelf") :
                    status.types[i] == "high-shelf" ? _("High Shelf") : _("Peak");
                labels[i].label = _("%g Hz · %s").printf (status.frequencies[i], kind);
                sliders[i].set_range (status.minimum[i], status.maximum[i]);
                sliders[i].set_value (gains[i]);
                values[i].label = _("%+.1f dB").printf (gains[i]);
            }
        }
        feedback.label = !matches ? _("No speaker equalizer profile is available for this output.") :
            status.error != "" ? status.error : status.busy ? _("Applying equalizer settings…") :
            !status.applied ? _("Waiting for audio before confirming the equalizer settings.") :
            equalizer.requested ? _("Equalizer settings applied.") : _("Equalizer is off.");
        updating = false;
    }
}
