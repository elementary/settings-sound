# Speaker equalizer controls

Sound consumes settings-daemon status and preferences; it does not own audio
processing. Closing Settings leaves enabled EQ and noise cancellation running.

The five gain controls are Bass, Low mids, Mids, Air and Upper balance. Their
names are fixed here; the device profile supplies frequencies, Q, gain ranges
and optional recommended gains. Frequencies appear in tooltips. Reset sits
below the sliders and preserves On/Off. Sliders remain editable while Off.

User preferences take precedence over recommendations. Invalid profiles remain
unavailable; a supported operation failure can be recovered by an explicit
changed preference after the daemon revalidates the graph.

Private integration checks use the companion daemon source and vendor marker policy
and profile, in the existing SDK without `/dev/snd`:

```
EQ_PRIVATE_TEST=1 EQ_OEM_RULE=<rule> EQ_OEM_PROFILE=<profile> \
    sh tests/run-components.sh <daemon-source>
```

The native bridge uses synthetic card/route metadata and private audio servers.
