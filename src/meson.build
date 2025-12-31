plug_files = files(
    'App.vala',
    'ApplicationsPanel.vala',
    'AppRow.vala',
    'CanberraGtk4.vala',
    'TestPopover.vala',
    'PulseAudioManager.vala',
    'Plug.vala',
    'OutputPanel.vala',
    'InputPanel.vala',
    'InputDeviceMonitor.vala',
    'DeviceRow.vala',
    'Device.vala'
)

switchboard_dep = dependency('switchboard-3')
switchboard_plugsdir = switchboard_dep.get_variable('plugsdir', pkgconfig_define: ['libdir', libdir])

shared_module(
    meson.project_name(),
    plug_files,
    config_file,
    plug_resources,
    dependencies: [
        dependency('glib-2.0'),
        dependency('gio-2.0'),
        dependency('gobject-2.0'),
        dependency('granite-7'),
        dependency('gtk4'),
        dependency('gtk4-x11'),
        dependency('libadwaita-1'),
        dependency('libpulse'),
        dependency('libpulse-mainloop-glib'),
        dependency('libcanberra'),
        meson.get_compiler('vala').find_library('libpulse-ext', dirs: join_paths(meson.project_source_root(), 'vapi')),
        switchboard_dep
    ],
    install: true,
    install_dir : join_paths(switchboard_plugsdir, 'system')
)
