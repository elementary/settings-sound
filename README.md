# Switchboard Sound Plug
[![Translation status](https://l10n.elementary.io/widgets/switchboard/switchboard-plug-sound/svg-badge.svg)](https://l10n.elementary.io/projects/switchboard/switchboard-plug-sound/?utm_source=widget)

![screenshot](data/screenshot.png?raw=true)

## Building and Installation

You'll need the following dependencies:

* libcanberra-gtk3-dev
* libgranite-dev
* libgtk-3-dev
* libpulse-dev
* libswitchboard-2.0-dev
* meson
* valac

Run `meson` to configure the build environment and then `ninja` to build

    meson build --prefix=/usr
    cd build
    ninja

To install, use `ninja install`

    sudo ninja install
