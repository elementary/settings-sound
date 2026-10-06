#!/usr/bin/env python3
"""Production Audio + EQ + Sound model over real private PW/Pulse/WP protocols.

The exported card has synthetic speaker/headphone Route metadata; no hardware
is exercised. Generic cases load the shipped WirePlumber graph policy.
"""
import json
import os
from pathlib import Path
import queue
import re
import select
import signal
import shutil
import subprocess
import tempfile
import threading
import time

assert os.environ.get('EQ_PRIVATE_TEST') == '1' and not Path('/dev/snd').exists()
base = Path(__file__).resolve().parent
generic_case = os.environ.get('EQ_GENERIC_CASE', '')
generic = bool(generic_case)
node_name = 'alsa_output.pci-0000_00_1f.3.analog-stereo' if generic else 'elementary.eq.test'
legacy = os.environ.get('EQ_LEGACY') == '1'
cache_probe = os.environ.get('EQ_TEST_CACHE_PARAMS') == '1'
restart_probe = os.environ.get('EQ_SERVER_RESTART_TEST') == '1'
evidence = base / ('bridge-server-restart-results' if restart_probe else 'bridge-generic-'+generic_case if generic else 'bridge-cache-results' if cache_probe else 'bridge-legacy-results' if legacy else 'bridge-results')
evidence.mkdir(exist_ok=True)
runtime = Path(tempfile.mkdtemp(prefix='vale-sound-eq-bridge-'))
profiles = Path(os.environ['EQ_TEST_PROFILE_DIR'])
assert profiles.parent.parent == Path.home() and profiles.parent.name.startswith('elementary-eq-bridge.')
profiles.mkdir(exist_ok=True)
daemon_source = Path(os.environ['EQ_DAEMON_SOURCE'])
profile_id = 'generic-speakers-v1' if generic else 'fixture-v1'
if generic_case.startswith('oem-'):
    profile_id = Path(os.environ['EQ_OEM_PROFILE']).stem
if generic:
    generic_profile = profiles/'generic-speakers-v1.ini'
    generic_profile.unlink(missing_ok=True)
    shutil.copyfile(daemon_source/'data/generic-speakers-v1.ini', generic_profile)
    profile_path = profiles/(profile_id+'.ini')
    if profile_path != generic_profile:
        profile_path.unlink(missing_ok=True)
        shutil.copyfile(generic_profile, profile_path)
    if generic_case in ('oem-valid', 'oem-independent-graph'):
        shutil.copyfile(os.environ['EQ_OEM_PROFILE'], profiles/(profile_id+'.ini'))
        if generic_case == 'oem-independent-graph':
            generic_profile.write_text(generic_profile.read_text().replace('Node=*', 'Node=alsa_output.other'))
    elif generic_case == 'oem-wildcard':
        path = profiles/(profile_id+'.ini')
        path.write_text(path.read_text().replace('DefaultGains=', 'DefaultGains=0;0;0;0;0;'))
    elif generic_case == 'oem-untrusted':
        path = profiles/(profile_id+'.ini')
        path.write_text(path.read_text().replace('Node=*', 'Node='+node_name).replace(
            'DefaultGains=', 'DefaultGains=0;0;0;0;0;'))
        path.chmod(0o666)
    elif generic_case == 'invalid-layout':
        path = profiles/(profile_id+'.ini')
        path.write_text(path.read_text().replace('Q=0.707;', 'Q=11;', 1))
    elif generic_case == 'untrusted':
        (profiles/(profile_id+'.ini')).chmod(0o666)
else:
    shutil.copyfile(os.environ['EQ_TEST_PROFILE'], profiles/'fixture-v1.ini')
    shutil.copyfile(daemon_source/'data/generic-speakers-v1.ini', profiles/'generic-speakers-v1.ini')

env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), PIPEWIRE_RUNTIME_DIR=str(runtime),
           PIPEWIRE_REMOTE='elementary-eq-bridge', PULSE_SERVER='unix:'+str(runtime/'native'),
           XDG_CONFIG_HOME=str(runtime/'user-config'), XDG_STATE_HOME=str(runtime/'state'),
           XDG_CACHE_HOME=str(runtime/'cache'), GSETTINGS_BACKEND='keyfile',
           GSETTINGS_SCHEMA_DIR=str(base/'schemas'))
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY', 'PIPEWIRE_CONFIG_PREFIX', 'PIPEWIRE_CONFIG_NAME', 'PIPEWIRE_CORE'):
    env.pop(key, None)
config = runtime/'config'
config.mkdir()
env['PIPEWIRE_CONFIG_DIR'] = str(config)
text = Path('/usr/share/pipewire/pipewire.conf').read_text()
text = text.replace('context.spa-libs = {', 'context.spa-libs = {\n    audiotestsrc = audiotestsrc/libspa-audiotestsrc')
text = re.sub(r'core.name\s*=\s*pipewire-0', 'core.name = elementary-eq-bridge', text)
(config/'pipewire.conf').write_text(text)
(config/'client.conf').write_text(Path('/usr/share/pipewire/client.conf').read_text())
(config/'pipewire-pulse.conf').write_text(Path('/usr/share/pipewire/pipewire-pulse.conf').read_text().replace('unix:native', 'unix:'+str(runtime/'native')))
if generic:
    env['EQ_TEST_GENERIC'] = '1'
    policy = Path(env['XDG_CONFIG_HOME'])/'wireplumber/wireplumber.conf.d'
    policy.mkdir(parents=True)
    shutil.copyfile(daemon_source/'data/50-elementary-speaker-equalizer.conf', policy/'50-elementary-speaker-equalizer.conf')
    if generic_case.startswith('oem-'):
        shutil.copyfile(os.environ['EQ_OEM_RULE'], policy/'51-vale-starfighter-physical-eq.conf')
if generic_case == 'oem-valid':
    schema_dir = runtime/'schemas'
    schema_dir.mkdir()
    shutil.copyfile(daemon_source/'data/io.elementary.settings-daemon.gschema.xml', schema_dir/'io.elementary.settings-daemon.gschema.xml')
    (schema_dir/'91-vendor.gschema.override').write_text('[io.elementary.settings-daemon.audio.equalizer]\nenabled=true\n')
    subprocess.run(['glib-compile-schemas', str(schema_dir)], check=True)
    env['GSETTINGS_SCHEMA_DIR'] = str(schema_dir)
processes, logs, commands, observations, checks = [], [], [], [], {}
last, failure = {}, None

def run(args, record=True):
    p = subprocess.run(args, env=env, text=True, capture_output=True, timeout=8)
    if record: commands.append(dict(argv=args, code=p.returncode, stdout=p.stdout, stderr=p.stderr))
    if p.returncode: raise RuntimeError((args, p.stderr))
    return p.stdout

def backend_status(record=False):
    return run(['gdbus', 'call', '--session', '--dest', 'io.elementary.settings-daemon',
        '--object-path', '/io/elementary/settings_daemon',
        '--method', 'io.elementary.settings_daemon.Audio.GetEqualizerStatus'], record)

def start(name, args, **kwargs):
    log = (evidence/(name+'.log')).open('w'); logs.append(log)
    p = subprocess.Popen(args, env=(dict(env,G_MESSAGES_DEBUG='all') if name=='audio-owner' else env), stderr=log, start_new_session=True, **(dict(stdout=log) | kwargs))
    processes.append(p)
    return p

def wait(fn, seconds=8):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        value = fn()
        if value: return value
        time.sleep(.05)
    raise TimeoutError((str(fn), last))

def check(name, value):
    checks[name] = bool(value)
    assert value, name

def objects(): return json.loads(run(['pw-dump'], False))
def sinks(): return json.loads(run(['pactl', '-f', 'json', 'list', 'sinks'], False))

def cli(lines):
    # Noninteractive pw-cli waits for registry discovery before each command.
    # A fresh interactive client can return zero despite "unknown global".
    for line in lines:
        args = line.split(' ', 3 if line.startswith('set-param ') else 2)
        output = run(['pw-cli', *args])
        assert 'Error:' not in output

def props(identifier=None):
    text = run(['pw-cli', 'enum-params', str(sink_id if identifier is None else identifier), 'Props'], False)
    values = {k:float(v) for k,v in re.findall(r'String "(eos_eq_[^"]+)"\s+Float ([-\d.eE+]+)', text)}
    return values

def bypassed(identifier=None):
    node = sink_id if identifier is None else identifier
    return not props(node) and 'eos_eq_' not in run(['pw-cli', 'enum-params', str(node), 'PropInfo'], False)

def curve(gains, headroom, identifier=None):
    values = props(identifier)
    return all(abs(values.get(f'eos_eq_{i+1}:Gain', 999)-g) < .001 for i,g in enumerate(gains)) and abs(values.get('eos_eq_h:Mult', 999)-headroom) < .00001

def receive():
    global last
    while not messages.empty(): last = messages.get_nowait()
    return last

def send(line):
    commands.append(dict(client=line, status=dict(last)))
    client.stdin.write(line+'\n'); client.stdin.flush()

def linked(enabled):
    for channel in ('FL', 'FR'):
        run(['pw-link', *([] if enabled else ['-d']),
             f'elementary.eq.tone:capture_{channel}', f'{node_name}:playback_{channel}'])

def native_clients():
    return [o for o in objects() if o['type']=='PipeWire:Interface:Client' and
            str(o.get('info',{}).get('props',{}).get('application.process.id'))==str(owner.pid) and
            o['info']['props'].get('client.api') != 'pipewire-pulse']

def create_fixture():
    cli([
        f'create-node adapter {{ factory.name = support.null-audio-sink node.name = {node_name} '
        f'media.class = Audio/Sink device.id = {card_id} card.profile.device = 0 '
        f'elementary.eq.profile = {profile_id} node.cache-params = '+('true' if cache_probe else 'false')+' audio.channels = 2 audio.position = [ FL FR ] '
        'priority.session = 1000 object.linger = true }',
        'create-node adapter { factory.name = audiotestsrc node.name = elementary.eq.tone '
        f'device.id = {card_id} card.profile.device = 1 '
        'media.class = Audio/Source audio.channels = 2 audio.position = [ FL FR ] '
        'priority.session = 2000 object.linger = true }'
    ])

try:
    bus = start('bus', ['dbus-daemon', '--session', '--nofork', '--print-address=1'], stdout=subprocess.PIPE, text=True)
    assert select.select([bus.stdout], [], [], 3)[0]
    env['DBUS_SESSION_BUS_ADDRESS'] = bus.stdout.readline().strip()
    server = start('pipewire', ['pipewire'])
    wait(lambda:(runtime/'elementary-eq-bridge').exists())
    card = start('card', [str(base/'bridge-device')], stdout=subprocess.PIPE, text=True)
    assert select.select([card.stdout], [], [], 3)[0]
    card_id = int(card.stdout.readline())
    if restart_probe:
        create_fixture()
    pulse = start('pulse', ['pipewire-pulse'])
    wireplumber = start('wireplumber', ['wireplumber'])
    wait(lambda:(runtime/'native').exists())
    if generic:
        marker = run([str(base/'graph-rules'), node_name]).strip()
        check('native_rule_order_selects_expected_profile', marker == profile_id)
        check('declared_invalid_profile_is_not_overridden',
              run([str(base/'graph-rules'), 'alsa_output.other', 'invalid-oem-v1']).strip() == 'invalid-oem-v1')
        check('non_alsa_output_has_no_generic_marker',
              run([str(base/'graph-rules'), 'bluez_output.fixture']).strip() == '')
    if not restart_probe:
        create_fixture()
    wait(lambda:any(s['name']==node_name for s in sinks()))
    if generic_case == 'oem-independent-graph':
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 1 device = 0 }'])
        wait(lambda:any(s['name'] == node_name and s['active_port'] == 'analog-output-headphones' for s in sinks()))
    sink = next(s for s in sinks() if s['name']==node_name)
    (evidence/'pulse-physical-fixture.json').write_text(json.dumps(sink, indent=2)+'\n')
    run(['pw-cli','info',str(card_id)])
    run(['pw-cli','enum-params',str(card_id),'EnumRoute'])
    run(['pw-cli','enum-params',str(card_id),'Route'])
    run(['pactl','-f','json','list','cards'])
    expected_route = 'analog-output-headphones' if generic_case == 'oem-independent-graph' else 'analog-output-speaker' if generic else 'fixture-speaker'
    check('real_pulse_card_and_active_route', 'HARDWARE' in sink['flags'] and sink['active_port']==expected_route)
    nodes = objects()
    sink_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name')==node_name)
    tone_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name')=='elementary.eq.tone')
    labels = ['bq_lowshelf', 'bq_peaking', 'bq_peaking', 'bq_peaking', 'bq_highshelf']
    graph_nodes = [dict(type='builtin', name=f'eos_eq_{i+1}', label=label, control=dict(Freq=freq, Q=q, Gain=0.0))
                   for i,(label,freq,q) in enumerate(zip(labels,[200,240,1000,16000,200],[.707,.6,1,6.606,.707]))]
    graph_nodes.append(dict(type='builtin', name='eos_eq_h', label='linear', control=dict(Mult=.25 if legacy else 1.0, Add=0.0)))
    links = [dict(output=f'eos_eq_{i}:Out', input=f'eos_eq_{i+1}:In') for i in range(1,5)]
    links.append(dict(output='eos_eq_5:Out', input='eos_eq_h:In'))
    graph = json.dumps(dict(nodes=graph_nodes, links=links))
    fmt = dict(mediaType='audio', mediaSubtype='raw', format='F32P', rate=48000, channels=2, position=['FL','FR'])
    cli([f'set-param {tone_id} PortConfig '+json.dumps(dict(direction='Output', mode='dsp', format=fmt)),
         f'set-param {sink_id} PortConfig '+json.dumps(dict(direction='Input', mode='dsp', format=fmt)),
         *([ ] if not (legacy or cache_probe) else [f'set-param {sink_id} Props '+json.dumps(dict(params=['audioconvert.filter-graph.0', graph]))]),
         f'set-param {sink_id} Props '+json.dumps(dict(channelVolumes=[.7,.35],mute=True))])
    for channel in ('FL','FR'): run(['pw-link', f'elementary.eq.tone:capture_{channel}', f'{node_name}:playback_{channel}'])
    run(['pw-cli','enum-params',str(sink_id),'PropInfo'])
    run(['pw-cli','enum-params',str(sink_id),'Props'])
    run(['pactl','set-default-sink',node_name])
    run(['pactl','set-default-source','elementary.eq.tone'])
    if generic_case == 'valid':
        hdmi_card = start('hdmi-card', ['env', 'EQ_TEST_HDMI=1', str(base/'bridge-device'), 'elementary.eq.hdmi-card'],
            stdout=subprocess.PIPE, text=True)
        assert select.select([hdmi_card.stdout], [], [], 3)[0]
        hdmi_card_id = int(hdmi_card.stdout.readline())
        hdmi_name = 'alsa_output.pci-0000_01_00.1.hdmi-stereo'
        check('native_hdmi_marker_is_generic', run([str(base/'graph-rules'), hdmi_name]).strip() == profile_id)
        cli([f'create-node adapter {{ factory.name = support.null-audio-sink node.name = {hdmi_name} '
             f'media.class = Audio/Sink device.id = {hdmi_card_id} card.profile.device = 0 '
             f'elementary.eq.profile = {profile_id} node.cache-params = false audio.channels = 2 '
             'audio.position = [ FL FR ] object.linger = true }'])
        wait(lambda:any(sink['name'] == hdmi_name for sink in sinks()))
        hdmi_id = next(o['id'] for o in objects() if o.get('info',{}).get('props',{}).get('node.name') == hdmi_name)
        run(['pactl','set-default-sink',hdmi_name])
    if not (legacy or cache_probe):
        check('no_graph_before_processing_is_enabled', bypassed())
    owner = start('audio-owner', [str(base/'bridge-audio-owner')])
    run(['gdbus','wait','--session','--timeout=5','io.elementary.settings-daemon'])
    env['GTK_A11Y']='none'
    client = start('sound-model', ['xvfb-run','-a',str(base/'bridge-client')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    messages = queue.Queue()
    def read():
        for line in client.stdout:
            item=json.loads(line); observations.append(item); messages.put(item)
    threading.Thread(target=read, daemon=True).start()
    if cache_probe:
        wait(lambda:bool(receive().get('error')))
        metadata = run(['pw-cli','enum-params',str(sink_id),'PropInfo'])
        check('cached_metadata_omits_installed_controls', 'eos_eq_' not in metadata and len(props())==48)
        check('cached_metadata_fails_closed', not last['applied'] and bool(last['error']))
        raise SystemExit(0)
    if generic:
        if generic_case == 'oem-independent-graph':
            wait(lambda:receive().get('available') and last.get('route') == 'analog-output-headphones')
            check('oem_other_route_uses_own_graph_with_neutral_defaults',
                  not last['enabled'] and last['gains'] == [0]*5 and last['defaults_count'] == 0)
            send('on')
            wait(lambda:receive().get('applied') and last.get('enabled') and curve([0]*5,1))
            check('unrelated_generic_profile_does_not_control_oem_route', True)
            # A valid new output must not be trapped by a removed old profile.
            shutil.copyfile(daemon_source/'data/generic-speakers-v1.ini', generic_profile)
            next_card = start('next-card', [str(base/'bridge-device'), 'elementary.eq.next-card'],
                stdout=subprocess.PIPE, text=True)
            assert select.select([next_card.stdout], [], [], 3)[0]
            next_card_id = int(next_card.stdout.readline())
            next_name = 'alsa_output.usb-next.analog-stereo'
            cli([f'create-node adapter {{ factory.name = support.null-audio-sink node.name = {next_name} '
                 f'media.class = Audio/Sink device.id = {next_card_id} card.profile.device = 0 '
                 'elementary.eq.profile = generic-speakers-v1 node.cache-params = false audio.channels = 2 '
                 'audio.position = [ FL FR ] object.linger = true }'])
            wait(lambda:any(s['name'] == next_name for s in sinks()))
            next_id = next(o['id'] for o in objects() if o.get('info',{}).get('props',{}).get('node.name') == next_name)
            cli([f'set-param {next_id} PortConfig '+json.dumps(dict(direction='Input',mode='dsp',format=fmt))])
            for channel in ('FL','FR'):
                run(['pw-link', f'elementary.eq.tone:capture_{channel}', f'{next_name}:playback_{channel}'])
            (profiles/(profile_id+'.ini')).unlink()
            run(['pactl','set-default-sink',next_name])
            wait(lambda:receive().get('node') == next_name and last.get('available') and last.get('applied'))
            check('removed_previous_profile_does_not_block_new_output', bypassed(next_id))
            raise SystemExit(0)
        if generic_case not in ('valid', 'oem-valid'):
            expected_error = {
                'untrusted': 'No valid root-installed equalizer profile is available.',
                'oem-untrusted': 'No valid root-installed equalizer profile is available.',
                'oem-empty': 'The equalizer profile is incomplete.',
                'oem-wildcard': 'The equalizer profile does not match the physical output.',
                'invalid-layout': 'An equalizer profile band is invalid.',
            }[generic_case]
            wait(lambda:expected_error in backend_status())
            check('intended_backend_profile_rejection', expected_error in backend_status(True))
            wait(lambda:bool(receive().get('error')) and not last['available'] and not last['applied'])
            check('declared_oem_or_untrusted_profile_fails_closed', True)
            send('on')
            time.sleep(.3)
            check('invalid_profile_enable_does_not_fallback', bypassed() and not receive()['available'])
            raise SystemExit(0)
        if generic_case == 'oem-valid':
            recommended = [7.5,8,-0.5,1.5,.5]
            wait(lambda:receive().get('available') and last.get('applied') and last.get('enabled') and curve(recommended,1))
            check('native_oem_recommendations_and_policy_start_on', last['gains'] == recommended)
            run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.]))])
            wait(lambda:receive().get('error') and last.get('available'))
            send('gtk-reset')
            time.sleep(.3)
            check('unchanged_oem_reset_does_not_authorize_failed_audit',
                  bool(receive().get('error')) and curve([-7,8,-0.5,1.5,.5],1))
            send('zero')
            wait(lambda:receive().get('applied') and last.get('gains') == [0]*5 and curve([0]*5,1))
            check('native_oem_explicit_zero_applies_unity', last['enabled'])
            send('gtk-reset')
            wait(lambda:receive().get('applied') and curve(recommended,1))
            send('gtk-gain 0 -6')
            wait(lambda:receive().get('applied') and curve([-6,8,-0.5,1.5,.5],1))
            send('gtk-toggle')
            wait(lambda:not receive().get('enabled',True) and last.get('applied') and bypassed())
            check('native_oem_off_retains_saved_gains', last['gains'] == [-6,8,-0.5,1.5,.5])
            path = profiles/(profile_id+'.ini')
            path.write_text(path.read_text().replace('DefaultGains=7.5;8;-0.5;1.5;0.5;', 'DefaultGains=0;0;0;0;0;'))
            send('gtk-toggle')
            wait(lambda:receive().get('enabled') and last.get('applied') and curve([-6,8,-0.5,1.5,.5],1))
            check('native_policy_refresh_preserves_personal_gains', True)
            send('gtk-reset')
            wait(lambda:receive().get('enabled') and last.get('applied') and
                 last.get('gains') == [0]*5 and curve([0]*5,1))
            check('native_oem_zero_reset_preserves_on_and_unity', True)
            raise SystemExit(0)
        wait(lambda:receive().get('available') and last.get('node') == hdmi_name)
        check('selected_hdmi_has_neutral_independent_preferences',
              not last['enabled'] and last['gains'] == [0]*5 and last['route'] == 'hdmi-output-0')
        run(['pactl','set-default-sink',node_name])
        wait(lambda:receive().get('node') == node_name and last.get('available') and last.get('applied'))
        check('hdmi_default_to_speakers_discovers_generic_eq', last['node'] == node_name)
        unused_card = start('unused-card', [str(base/'bridge-device'), 'elementary.eq.unused-card'],
            stdout=subprocess.PIPE, text=True)
        assert select.select([unused_card.stdout], [], [], 3)[0]
        unused_card_id = int(unused_card.stdout.readline())
        unused_name = 'alsa_output.usb-unused.analog-stereo'
        cli([f'create-node adapter {{ factory.name = support.null-audio-sink node.name = {unused_name} '
             f'media.class = Audio/Sink device.id = {unused_card_id} card.profile.device = 0 '
             f'elementary.eq.profile = {profile_id} node.cache-params = false audio.channels = 2 '
             'audio.position = [ FL FR ] object.linger = true }'])
        wait(lambda:any(sink['name'] == unused_name for sink in sinks()))
        unused_id = next(o['id'] for o in objects() if o.get('info',{}).get('props',{}).get('node.name') == unused_name)
        check('never_started_output_has_no_initialized_controls', 'eos_eq_1:Gain' not in props(unused_id))
        run(['pactl','set-default-sink',unused_name])
        wait(lambda:receive().get('node') == unused_name and last.get('available') and not last.get('busy'))
        check('never_started_off_output_needs_no_graph', last['applied'] and not last['error'] and bypassed(unused_id))
        run(['pactl','set-default-sink',node_name])
        wait(lambda:receive().get('node') == node_name and last.get('applied'))
        check('never_started_default_switch_releases_untouched_graph', 'eos_eq_1:Gain' not in props(unused_id))
        run(['pw-cli','destroy',str(unused_id)])
        run(['pw-cli','destroy',str(hdmi_id)])
        check('generic_defaults_are_empty', last['defaults_count'] == 0 and last['gains'] == [0]*5)
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.0',graph]))])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.]))])
        wait(lambda:receive().get('error') and last.get('available') and not last.get('applied') and not last.get('busy'))
        check('generic_off_failure_remains_supported', not last['enabled'] and last['gtk_switch_sensitive'])
        send('gtk-toggle')
        wait(lambda:receive().get('enabled') and last.get('applied') and curve([0]*5,1))
        check('generic_explicit_on_from_off_failure_revalidates', True)
        time.sleep(.5)
        wait(lambda:receive().get('applied') and not last.get('busy'))
        check('generic_flat_is_unity', curve([0]*5,1))
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.]))])
        wait(lambda:receive().get('error') and last.get('gtk_switch_sensitive') and last.get('available') and not last.get('applied'))
        check('generic_normalized_default_stays_failed', last['gains'] == [0]*5 and curve([-7,0,0,0,0],1))
        send('gtk-toggle')
        wait(lambda:not receive().get('enabled',True) and last.get('applied') and bypassed())
        check('generic_failed_off_recovers_with_normalized_default', True)
        send('on')
        wait(lambda:receive().get('enabled') and last.get('applied'))
        send('gtk-gain 0 3')
        wait(lambda:receive().get('applied') and curve([3,0,0,0,0],1))
        check('generic_custom_boost_keeps_unity_gain', True)
        send('gtk-gain 1 12')
        wait(lambda:receive().get('applied') and curve([3,12,0,0,0],1))
        check('twelve_db_bass_boost_does_not_reduce_global_gain', True)
        send('gtk-gain 1 0')
        wait(lambda:receive().get('applied') and curve([3,0,0,0,0],1))
        send('gtk-gain 0 0')
        wait(lambda:receive().get('applied') and curve([0]*5,1))
        check('generic_zero_custom_has_unity_headroom', True)
        send('gtk-gain 0 -6')
        wait(lambda:receive().get('applied') and curve([-6,0,0,0,0],1))
        check('generic_cut_only_keeps_unity_gain', True)
        send('gtk-gain 0 3')
        wait(lambda:receive().get('applied') and curve([3,0,0,0,0],1))
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 1 device = 0 }'])
        wait(lambda:receive().get('route')=='analog-output-headphones' and bypassed())
        send('select-output '+node_name+' analog-output-headphones')
        wait(lambda:receive().get('gtk_switch_sensitive'))
        check('generic_headphones_have_neutral_independent_preferences',
              last['available'] and not last['enabled'] and last['gains'] == [0]*5)
        send('gtk-toggle')
        wait(lambda:receive().get('enabled') and last.get('applied'))
        send('gtk-gain 0 -6')
        wait(lambda:receive().get('applied') and last.get('gains') == [-6,0,0,0,0] and
             curve([-6,0,0,0,0],1))
        check('selected_headphone_slider_reaches_native_graph', True)
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.]))])
        wait(lambda:receive().get('error') and last.get('available'))
        send('gtk-toggle')
        wait(lambda:not receive().get('enabled',True) and not last.get('error') and bypassed())
        check('explicit_off_on_headphones_revalidates_failed_bypass', last['gains'] == [-6,0,0,0,0])
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 0 device = 0 }'])
        send('select-output '+node_name+' analog-output-speaker')
        wait(lambda:receive().get('route') == 'analog-output-speaker' and last.get('enabled') and
             last.get('applied') and last.get('gains') == [3,0,0,0,0] and curve([3,0,0,0,0],1))
        check('speaker_route_keeps_its_enabled_preference_and_gains', True)
        usb_card = start('usb-card', [str(base/'bridge-device'), 'elementary.eq.usb-card'],
            stdout=subprocess.PIPE, text=True)
        assert select.select([usb_card.stdout], [], [], 3)[0]
        usb_card_id = int(usb_card.stdout.readline())
        usb_name = 'alsa_output.usb-fixture.analog-stereo'
        cli([f'create-node adapter {{ factory.name = support.null-audio-sink node.name = {usb_name} '
             f'media.class = Audio/Sink device.id = {usb_card_id} card.profile.device = 0 '
             f'elementary.eq.profile = {profile_id} node.cache-params = false audio.channels = 2 '
             'audio.position = [ FL FR ] object.linger = true }'])
        wait(lambda:any(sink['name'] == usb_name for sink in sinks()))
        usb_id = next(o['id'] for o in objects() if o.get('info',{}).get('props',{}).get('node.name') == usb_name)
        cli([f'set-param {usb_id} PortConfig '+json.dumps(dict(direction='Input',mode='dsp',format=fmt))])
        for channel in ('FL','FR'):
            run(['pw-link', f'elementary.eq.tone:capture_{channel}', f'{usb_name}:playback_{channel}'])
        linked(False)
        wait(lambda:any(o['id'] == sink_id and o.get('info',{}).get('state') == 'idle' for o in objects()))
        owner.terminate()
        owner.wait(timeout=3)
        owner = start('restarted-audio-owner', [str(base/'bridge-audio-owner')])
        run(['gdbus','wait','--session','--timeout=5','io.elementary.settings-daemon'])
        wait(lambda:receive().get('node') == node_name and last.get('available') and not last.get('busy')
             and not last.get('applied') and node_name in backend_status())
        check('restarted_backend_preserves_idle_controls_before_explicit_switch',
              not last['applied'] and curve([3,0,0,0,0],1))
        run(['pactl','set-default-sink',usb_name])
        wait(lambda:receive().get('node') == usb_name and last.get('available') and last.get('applied'))
        check('two_speaker_defaults_retire_idle_old_graph', bypassed() and bypassed(usb_id))
        check('new_output_hides_old_physical_panel', not last['gtk_switch_sensitive'])
        send('on')
        time.sleep(.5)
        send('gain')
        wait(lambda:receive().get('applied') and curve([-6,0,0,0,0],1,usb_id))
        check('second_output_custom_uses_its_own_preferences', bypassed())
        linked(True)
        run(['pactl','set-default-sink',node_name])
        wait(lambda:receive().get('node') == node_name and last.get('applied') and curve([3,0,0,0,0],1))
        check('return_to_first_output_restores_preferences_and_removes_second_graph', bypassed(usb_id))
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Freq',201.]))])
        wait(lambda:receive().get('error') and not last.get('applied'))
        run(['pactl','set-default-sink',usb_name])
        wait(lambda:receive().get('node') == usb_name and last.get('applied') and curve([-6,0,0,0,0],1,usb_id))
        check('failed_retirement_does_not_block_another_output', curve([3,0,0,0,0],1) and props()['eos_eq_1:Freq'] == 201.)
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Freq',200.]))])
        run(['pactl','set-default-sink',node_name])
        wait(lambda:receive().get('node') == node_name and last.get('applied') and curve([3,0,0,0,0],1))
        run(['pw-cli','destroy',str(usb_id)])
        send('gtk-reset')
        wait(lambda:receive().get('applied') and curve([0]*5,1))
        check('generic_reset_to_flat_unity', True)
        check('no_second_visible_output', len(sinks()) == 1)
        raise SystemExit(0)
    wait(lambda:receive().get('available') and last.get('applied'))
    if not legacy: check('initial_off_has_no_graph', bypassed())
    send('on')
    wait(lambda:receive().get('enabled') and last.get('applied') and curve([-1,-2,-3,-4,-5],1))
    check('model_daemon_pulse_native_default_applied', True)
    if restart_probe:
        old_properties = next(o['info']['props'] for o in objects() if o['id'] == sink_id)
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        wait(lambda:receive().get('error') and not last.get('applied'))
        for process in (wireplumber, pulse, card, server):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        wait(lambda:not receive().get('available'))
        # Keep the reconnecting owner from allocating globals before the
        # replacement fixture has recreated the original IDs.
        owner.send_signal(signal.SIGSTOP)
        try:
            server = start('new-pipewire', ['pipewire'])
            wait(lambda:(runtime/'elementary-eq-bridge').exists())
            card = start('new-card', [str(base/'bridge-device')], stdout=subprocess.PIPE, text=True)
            assert select.select([card.stdout], [], [], 3)[0]
            card_id = int(card.stdout.readline())
            create_fixture()
            pulse = start('new-pulse', ['pipewire-pulse'])
            wireplumber = start('new-wireplumber', ['wireplumber'])
            wait(lambda:(runtime/'native').exists())
            wait(lambda:any(s['name'] == node_name for s in sinks()))
            nodes = objects()
            sink_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name') == node_name)
            tone_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name') == 'elementary.eq.tone')
            cli([f'set-param {tone_id} PortConfig '+json.dumps(dict(direction='Output',mode='dsp',format=fmt)),
                 f'set-param {sink_id} PortConfig '+json.dumps(dict(direction='Input',mode='dsp',format=fmt))])
            linked(True)
            run(['pactl','set-default-sink',node_name])
        finally:
            owner.send_signal(signal.SIGCONT)
        wait(lambda:receive().get('enabled') and last.get('applied') and curve([-1,-2,-3,-4,-5],1), 15)
        check('new_server_restores_saved_eq_after_failed_old_graph', owner.poll() is None)
        new_properties = next(o['info']['props'] for o in objects() if o['id'] == sink_id)
        identity_keys = ('object.serial', 'device.id')
        (evidence/'server-restart.json').write_text(json.dumps(dict(
            before={key:old_properties[key] for key in identity_keys},
            after={key:new_properties[key] for key in identity_keys}))+'\n')
        check('new_server_reuses_request_identifiers',
              all(old_properties[key] == new_properties[key] for key in identity_keys))
        send('off')
        wait(lambda:receive().get('applied') and bypassed())
        check('new_server_off_removes_graph', True)
        raise SystemExit(0)
    settings_path = re.search(r'/io/elementary/settings-daemon/audio/equalizer/[0-9a-f]+/', backend_status()).group()
    schema = 'io.elementary.settings-daemon.audio.equalizer:' + settings_path
    run(['gsettings','set',schema,'gains','[1000., -2., -3., -4., -5.]'])
    wait(lambda:receive().get('error') and not last.get('applied'))
    run(['gsettings','set',schema,'gains','[-1., -2., -3., -4., -5.]'])
    wait(lambda:receive().get('applied') and not last.get('error') and curve([-1,-2,-3,-4,-5],1))
    check('repair_to_last_valid_gains_recovers_validation_failure', True)
    subscriber = start('pulse-events', ['pactl','subscribe'], stdout=subprocess.PIPE, text=True)
    events=[]
    def read_events():
        for line in subscriber.stdout: events.append(line.strip())
    threading.Thread(target=read_events, daemon=True).start()
    time.sleep(.2)
    run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.0]))])
    if not legacy:
        wait(lambda:receive().get('error') and curve([-7,-2,-3,-4,-5],1))
    for value in ('0','1','0','1'):
        run(['pw-cli','set-param',str(sink_id),'Props','{ mute = '+('true' if value=='1' else 'false')+' }']); time.sleep(.15)
    wait(lambda:any('sink #' in e for e in events))
    time.sleep(2)
    receive()
    (evidence/'foreign-after-pulse-events.json').write_text(json.dumps(dict(status=last, controls=props(), events=events),indent=2)+'\n')
    if legacy:
        check('legacy_reproduces_foreign_gain_overwrite', curve([-1,-2,-3,-4,-5],1))
    else:
        check('foreign_gain_survives_real_sink_events', curve([-7,-2,-3,-4,-5],1))
        check('native_failed_audit_survives_rediscovery', last['available'] and not last['applied'] and bool(last['error']))
        send('on'); time.sleep(.3)
        check('unchanged_enable_does_not_retry_failed_audit', curve([-7,-2,-3,-4,-5],1))
        send('gain')
        wait(lambda:receive().get('applied') and curve([-6,-2,-3,-4,-5],1))
        check('explicit_gain_change_revalidates_supported_failed_output', True)
        send('reset')
        wait(lambda:receive().get('applied') and curve([-1,-2,-3,-4,-5],1))
        send('off')
        wait(lambda:not receive().get('enabled',True) and last.get('applied') and bypassed())
        wait(lambda:receive().get('gtk_switch_sensitive') and last.get('aec_available'))
        send('aec-on')
        wait(lambda:receive().get('aec_enabled') and not last.get('aec_busy') and last.get('applied') and last.get('gtk_switch_sensitive'))
        send('gtk-toggle')
        wait(lambda:receive().get('gtk_on') and last.get('applied') and curve([-1,-2,-3,-4,-5],1))
        check('real_gtk_enable_with_owned_aec', last['aec_enabled'] and not last['aec_error'])
        for band in range(5): send(f'gtk-gain {band} {-7+band}')
        wait(lambda:receive().get('applied') and curve([-7,-6,-5,-4,-3],1))
        check('all_five_real_gtk_sliders_reach_native_controls', last['aec_enabled'])
        send('gtk-zero')
        wait(lambda:receive().get('applied') and curve([0]*5,1))
        check('real_gtk_flat_unity_with_owned_aec', last['aec_enabled'])
        send('gtk-reset')
        wait(lambda:receive().get('applied') and curve([-1,-2,-3,-4,-5],1))
        check('real_gtk_reset_with_owned_aec', last['aec_enabled'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        wait(lambda:receive().get('error') and last.get('gtk_switch_sensitive') and last.get('gtk_bands_sensitive'))
        send('gtk-toggle')
        wait(lambda:not receive().get('gtk_on',True) and last.get('applied') and bypassed())
        check('real_gtk_failed_off_recovers_unity_with_owned_aec', last['aec_enabled'])
        send('aec-off')
        wait(lambda:not receive().get('aec_enabled',True) and not last.get('aec_busy'))
        check('owned_aec_disables_without_attaching_eq', bypassed())
        check('failed_off_withdraws_preference_and_bypasses', True)
        send('on'); wait(lambda:receive().get('enabled') and last.get('applied') and curve([-1,-2,-3,-4,-5],1))
        send('zero'); wait(lambda:receive().get('applied') and curve([0]*5,1))
        check('enabled_flat_has_unity_headroom', True)
        send('reset'); wait(lambda:receive().get('applied') and curve([-1,-2,-3,-4,-5],1))
        send('gain'); wait(lambda:receive().get('applied') and curve([-6,-2,-3,-4,-5],1))
        check('explicit_custom_keeps_unity_gain', True)
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 1 device = 0 }'])
        wait(lambda:receive().get('route')=='fixture-headphones' and bypassed())
        check('headphones_do_not_inherit_oem_recommendations',
              last['available'] and not last['enabled'] and last['defaults_count'] == 0 and last['gains'] == [0]*5)
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 0 device = 0 }'])
        wait(lambda:receive().get('route')=='fixture-speaker' and last.get('applied') and curve([-6,-2,-3,-4,-5],1))
        check('speaker_route_return_reapplies_preferences', True)
        linked(False)
        wait(lambda:not receive().get('applied'))
        time.sleep(1.2)
        linked(True)
        wait(lambda:receive().get('applied') and curve([-6,-2,-3,-4,-5],1))
        check('unchanged_idle_resume_confirms_read_only', True)
        for control, value, expected, headroom in (
                ('eos_eq_1:Gain', -7., [-7,-2,-3,-4,-5], 1),
                ('eos_eq_h:Mult', .125, [-6,-2,-3,-4,-5], .125)):
            linked(False)
            wait(lambda:not receive().get('applied'))
            time.sleep(1.2)
            run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=[control,value]))])
            linked(True)
            wait(lambda:receive().get('error') and not last['applied'])
            time.sleep(1.2)
            check('foreign_idle_'+control.split(':')[1]+'_survives_resume', curve(expected,headroom))
            send('off')
            wait(lambda:not receive().get('enabled',True) and last.get('applied') and bypassed())
            send('on')
            wait(lambda:receive().get('enabled') and last.get('applied') and curve([-6,-2,-3,-4,-5],1))
        clients = native_clients()
        (evidence/'clients.json').write_text(json.dumps([o for o in objects() if o['type']=='PipeWire:Interface:Client'],indent=2)+'\n')
        check('exactly_one_native_client', len(clients)==1)
        run(['pw-cli','destroy',str(clients[0]['id'])])
        wait(lambda:receive().get('error') and not last['applied'])
        wait(lambda:receive().get('applied') and len(native_clients())==1)
        check('native_disconnect_reconnect_same_owner', owner.poll() is None and curve([-6,-2,-3,-4,-5],1))
        # A disconnected client must not regain write permission for its old request.
        run(['pw-cli','destroy',str(native_clients()[0]['id'])])
        wait(lambda:receive().get('error') and not last['applied'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        time.sleep(3.5)
        receive()
        check('foreign_gain_survives_reconnect', bool(last['error']) and not last['applied'] and curve([-8,-2,-3,-4,-5],1))
        pulse.terminate()
        pulse.wait(timeout=3)
        wait(lambda:not receive().get('available'))
        pulse = start('pulse-restarted', ['pipewire-pulse'])
        wait(lambda:(runtime/'native').exists())
        wait(lambda:receive().get('available') and bool(last['error']))
        time.sleep(.5)
        check('pulse_bridge_restart_retains_failure_and_foreign_gains',
              owner.poll() is None and not last['applied'] and curve([-8,-2,-3,-4,-5],1))
        send('off')
        wait(lambda:not receive().get('enabled',True) and last.get('applied') and bypassed())
        send('invalid-gains')
        time.sleep(.3)
        check('nonfinite_out_of_range_and_invalid_band_refused', bypassed())
        linked(False)
        wait(lambda:next(o['info']['state'] for o in objects() if o['id'] == sink_id) in ('idle', 'suspended'))
        wait(lambda:receive().get('applied') and bypassed())
        send('on')
        # The preference arrives before the daemon has reconciled the request.
        wait(lambda:receive().get('enabled') and not last.get('busy') and not last.get('applied'))
        check('explicit_idle_request_waits_for_running_node', bypassed())
        run(['pw-cli','destroy',str(native_clients()[0]['id'])])
        wait(lambda:receive().get('error'))
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.0',graph]))])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        linked(True)
        wait(lambda:len(native_clients()) == 1 and receive().get('error') and not last.get('applied'))
        time.sleep(.5)
        check('idle_write_authority_is_revoked_on_disconnect', curve([-8,0,0,0,0],1))
        send('off')
        wait(lambda:receive().get('applied') and bypassed())
        linked(False)
        wait(lambda:next(o['info']['state'] for o in objects() if o['id'] == sink_id) in ('idle', 'suspended'))
        wait(lambda:receive().get('applied') and bypassed())
        send('on')
        wait(lambda:receive().get('enabled') and not last.get('busy') and not last.get('applied'))
        send('off')
        wait(lambda:not receive().get('enabled',True) and not last.get('busy'))
        linked(True)
        wait(lambda:receive().get('applied') and bypassed())
        check('superseded_idle_request_never_applies_old_gains', True)
        # Queue a real Props notification while the owner is stopped, then stall
        # the server before allowing its async audit to issue enumeration.
        owner.send_signal(signal.SIGSTOP)
        run(['pw-cli','set-param',str(sink_id),'Props','{ mute = false }'])
        server.send_signal(signal.SIGSTOP)
        started = time.monotonic()
        owner.send_signal(signal.SIGCONT)
        try:
            wait(lambda:receive().get('error')=='The PipeWire equalizer connection failed.', 3.5)
            elapsed = time.monotonic()-started
            check('stalled_native_audit_deadline_disconnects', 1.8 <= elapsed < 3.5 and not last['applied'])
            (evidence/'deadline.json').write_text(json.dumps(dict(seconds=elapsed,status=last),indent=2)+'\n')
        finally:
            server.send_signal(signal.SIGCONT)
        wait(lambda:receive().get('applied') and len(native_clients())==1)
        check('deadline_cancellation_reconnects_without_old_write', bypassed())
        # A profile marker does not grant ownership of an existing graph.
        # Exercise both ordinary foreign controls and a graph with no controls.
        for foreign in (
            dict(nodes=[dict(type='builtin',name='foreign',label='linear',control=dict(Mult=.7))]),
            dict(nodes=[dict(type='builtin',name='foreign',label='copy')]),
        ):
            run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.0',json.dumps(foreign)]))])
            wait(lambda:receive().get('error') and not last['applied'])
            before_foreign = run(['pw-cli','enum-params',str(sink_id),'Props'])
            send('on')
            wait(lambda:receive().get('enabled') and last.get('error') and not last['busy'])
            time.sleep(.3)
            check('foreign_graph_'+foreign['nodes'][0]['label']+'_survives_enable',
                  before_foreign == run(['pw-cli','enum-params',str(sink_id),'Props']) and not last['applied'])
            send('off')
            wait(lambda:not receive().get('enabled') and last.get('error') and not last['busy'])
            check('foreign_graph_'+foreign['nodes'][0]['label']+'_survives_disable',
                  before_foreign == run(['pw-cli','enum-params',str(sink_id),'Props']))
            run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.0','']))])
            send('on')
            wait(lambda:receive().get('applied') and not last['error'])
            send('off')
            wait(lambda:receive().get('applied') and bypassed())
        run(['pw-cli','set-param',str(sink_id),'Props','{ mute = true }'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.0',graph,'audioconvert.filter-graph.1',graph]))])
        wait(lambda:receive().get('error') and not last['applied'])
        check('duplicate_reserved_namespace_fails_closed', not last['applied'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.1','']))])
        # A real changed preference is required to recover a failed audit.
        send('off')
        time.sleep(.3)
        check('unchanged_off_cannot_reset_failed_audit', bool(receive().get('error')))
        actual = run(['pw-cli','enum-params',str(sink_id),'Props'])
        check('physical_balance_preserved', re.search(r'Float 0.700000\s+Float 0.350000',actual))
        check('physical_mute_preserved', re.search(r'Props:mute .*?\n\s+Bool true',actual))
        old_serial = next(o['info']['props']['object.serial'] for o in objects() if o['id']==sink_id)
        run(['pw-cli','destroy',str(sink_id)])
        wait(lambda:not receive().get('available') and not last.get('applied'))
        check('node_removal_revokes_confirmation', True)
        cli(['create-node adapter { factory.name = support.null-audio-sink node.name = elementary.eq.test '
             f'media.class = Audio/Sink device.id = {card_id} card.profile.device = 0 '
             'elementary.eq.profile = fixture-v1 node.cache-params = false audio.channels = 2 '
             'audio.position = [ FL FR ] priority.session = 1000 object.linger = true }'])
        wait(lambda:any(s['name']==node_name for s in sinks()))
        replacement = next(o for o in objects() if o.get('info',{}).get('props',{}).get('node.name')=='elementary.eq.test')
        sink_id = replacement['id']
        graph_nodes[0]['control']['Freq']=106.
        bad_graph=json.dumps(dict(nodes=graph_nodes,links=links))
        cli([f'set-param {sink_id} PortConfig '+json.dumps(dict(direction='Input',mode='dsp',format=fmt)),
             f'set-param {sink_id} Props '+json.dumps(dict(params=['audioconvert.filter-graph.0',bad_graph]))])
        run(['pactl','set-default-sink',node_name])
        linked(True)
        wait(lambda:receive().get('error')=='The equalizer does not match its installed profile.')
        check('replacement_serial_with_mismatched_graph_refused', replacement['info']['props']['object.serial']!=old_serial and not last['applied'])
except Exception as exc:
    failure=repr(exc)
    raise
finally:
    if failure and 'sink_id' in globals():
        try:
            run(['pw-cli','enum-params',str(sink_id),'PropInfo'])
            run(['pw-cli','enum-params',str(sink_id),'Props'])
        except Exception: pass
    for p in reversed(processes):
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGCONT)
            os.killpg(p.pid, signal.SIGTERM)
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL); p.wait()
    for log in logs: log.close()
    (evidence/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    (evidence/'observations.json').write_text(json.dumps(observations,indent=2)+'\n')
    (evidence/'checks.json').write_text(json.dumps(dict(checks=checks,failure=failure,runtime=str(runtime)),indent=2)+'\n')
    shutil.rmtree(runtime)
print(json.dumps(checks))
