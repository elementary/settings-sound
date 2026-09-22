i18n.merge_file(
    input: 'sound.metainfo.xml.in',
    output: meson.project_name() + '.metainfo.xml',
    po_dir: meson.project_source_root() / 'po' / 'extra',
    type: 'xml',
    install: true,
    install_dir: datadir / 'metainfo',
)

install_data(
    'sound.gschema.xml',
    install_dir: datadir / 'glib-2.0' / 'schemas'
)
