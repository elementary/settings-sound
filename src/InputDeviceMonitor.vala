// -*- Mode: vala; indent-tabs-mode: nil; tab-width: 4 -*-
/*-
 * Copyright (c) 2016-2017 elementary LLC. (https://elementary.io)
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
 * Boston, MA 02110-1301 USA.
 *
 * Authored by: Corentin Noël <corentin@elementary.io>
 */

public class Sound.InputDeviceMonitor : GLib.Object {
    public signal void update_fraction (float fraction);
    private PulseAudio.Stream steam;
    private unowned Device device;
    private bool allow_record = false;

    public InputDeviceMonitor () {

    }

    ~InputDeviceMonitor () {
        if (steam != null) {
            steam.set_read_callback (null);
            steam.set_suspended_callback (null);
            steam.disconnect ();
        }
    }

    public void stop_record () {
        if (allow_record == false) {
            return;
        }

        allow_record = false;

        if (steam != null) {
            steam.disconnect ();
            steam = null;
        }
    }

    public void start_record () {
        allow_record = true;

        if (device == null) {
            return;
        }

        if (steam != null) {
            steam.disconnect ();
            steam = null;
        }

        unowned PulseAudio.Context c = PulseAudioManager.get_default ().context;
        var ss = PulseAudio.SampleSpec () {
            format = PulseAudio.SampleFormat.FLOAT32NE,
            rate = 25,
            channels = 1
        };

        var props = new PulseAudio.Proplist ();
        props.sets (PulseAudio.Proplist.PROP_APPLICATION_NAME, "Sound Settings");
        props.sets (PulseAudio.Proplist.PROP_APPLICATION_ID, "io.elementary.settings.sound");
        props.sets (PulseAudio.Proplist.PROP_APPLICATION_ICON_NAME, "multimedia-volume-control");
        props.sets (PulseAudio.Proplist.PROP_APPLICATION_VERSION, "0.1");

        steam = new PulseAudio.Stream (c, _("Peak detect"), ss, null, props);
        steam.set_read_callback (steam_read_callback);
        steam.set_suspended_callback (steam_suspended_callback);

        var a = PulseAudio.Stream.BufferAttr () {
            maxlength = uint32.MAX,
            fragsize = (uint32)sizeof (float)
        };
        steam.connect_record ("%u".printf (device.source_index), a, PulseAudio.Stream.Flags.DONT_MOVE | PulseAudio.Stream.Flags.PEAK_DETECT | PulseAudio.Stream.Flags.ADJUST_LATENCY);
    }

    public void set_device (Device device) {
        this.device = device;
        if (allow_record) {
            start_record ();
        } else {
            stop_record ();
        }
    }

    private void steam_read_callback (PulseAudio.Stream s, size_t nbytes) {
        void *data;
        if (s.peek (out data, out nbytes) < 0) {
            warning ("Failed to read data from stream");
            return;
        }

        if (data == null) {
            s.drop ();
            return;
        }

        float v = ((float[]) data)[nbytes / sizeof (float) - 1];
        s.drop ();

        if (v < 0) {
            v = 0;
        }

        if (v > 1) {
            v = 1;
        }

        update_fraction (v);
    }

    private void steam_suspended_callback (PulseAudio.Stream s) {
        update_fraction (0);
    }
}
