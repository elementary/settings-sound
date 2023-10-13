# Sound Settings
[![Translation status](https://l10n.elementary.io/widgets/switchboard/-/switchboard-plug-sound/svg-badge.svg)](https://l10n.elementary.io/engage/switchboard/?utm_source=widget)

![screenshot](data/screenshot-output.png?raw=true)

## Building and Installation

You'll need the following dependencies:

* libadwaita-1-dev
* libcanberra-gtk4-dev
* libgranite-7-dev
* libgtk-4-dev
* libpulse-dev
* libswitchboard-3-dev
* meson
* valac

Run `meson` to configure the build environment and then `ninja` to build

    meson build --prefix=/usr
    cd build
    ninja

To install, use `ninja install`

    ninja install
