#!/usr/bin/env python3
"""Production Audio + EQ + Sound model over real private PW/Pulse/WP protocols.

The exported card has synthetic speaker/headphone Route metadata; no hardware
or production policy is claimed. The fixture alone installs the DSP graph.
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
legacy = os.environ.get('EQ_LEGACY') == '1'
cache_probe = os.environ.get('EQ_TEST_CACHE_PARAMS') == '1'
evidence = base / ('bridge-cache-results' if cache_probe else 'bridge-legacy-results' if legacy else 'bridge-results')
evidence.mkdir(exist_ok=True)
runtime = Path(tempfile.mkdtemp(prefix='vale-sound-eq-bridge-'))
profiles = Path(os.environ['EQ_TEST_PROFILE_DIR'])
assert profiles.parent.parent == Path('/root') and profiles.parent.name.startswith('elementary-eq-bridge.')
profiles.mkdir()
shutil.copyfile(os.environ['EQ_TEST_PROFILE'], profiles/'fixture-v1.ini')
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), PIPEWIRE_RUNTIME_DIR=str(runtime),
           PIPEWIRE_REMOTE='elementary-eq-bridge', PULSE_SERVER='unix:'+str(runtime/'native'),
           XDG_CONFIG_HOME=str(runtime/'user-config'), XDG_STATE_HOME=str(runtime/'state'),
           XDG_CACHE_HOME=str(runtime/'cache'), GSETTINGS_BACKEND='keyfile',
           GSETTINGS_SCHEMA_DIR=str(base/'schemas'))
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY', 'PIPEWIRE_CONFIG_PREFIX', 'PIPEWIRE_CONFIG_NAME'):
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
processes, logs, commands, observations, checks = [], [], [], [], {}
last, failure = {}, None

def run(args, record=True):
    p = subprocess.run(args, env=env, text=True, capture_output=True, timeout=8)
    if record: commands.append(dict(argv=args, code=p.returncode, stdout=p.stdout, stderr=p.stderr))
    if p.returncode: raise RuntimeError((args, p.stderr))
    return p.stdout

def start(name, args, **kwargs):
    log = (evidence/(name+'.log')).open('w'); logs.append(log)
    p = subprocess.Popen(args, env=(dict(env,G_MESSAGES_DEBUG='all') if name=='audio-owner' else env), stderr=log, **(dict(stdout=log) | kwargs))
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

def props():
    text = run(['pw-cli', 'enum-params', str(sink_id), 'Props'], False)
    values = {k:float(v) for k,v in re.findall(r'String "(eos_eq_[^"]+)"\s+Float ([-\d.eE+]+)', text)}
    return values

def curve(gains, headroom):
    values = props()
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
             f'elementary.eq.tone:capture_{channel}', f'elementary.eq.test:playback_{channel}'])

def native_clients():
    return [o for o in objects() if o['type']=='PipeWire:Interface:Client' and
            str(o.get('info',{}).get('props',{}).get('application.process.id'))==str(owner.pid) and
            o['info']['props'].get('client.api') != 'pipewire-pulse']

try:
    bus = start('bus', ['dbus-daemon', '--session', '--nofork', '--print-address=1'], stdout=subprocess.PIPE, text=True)
    assert select.select([bus.stdout], [], [], 3)[0]
    env['DBUS_SESSION_BUS_ADDRESS'] = bus.stdout.readline().strip()
    server = start('pipewire', ['pipewire'])
    wait(lambda:(runtime/'elementary-eq-bridge').exists())
    card = start('card', [str(base/'bridge-device')], stdout=subprocess.PIPE, text=True)
    assert select.select([card.stdout], [], [], 3)[0]
    card_id = int(card.stdout.readline())
    start('pulse', ['pipewire-pulse'])
    start('wireplumber', ['wireplumber'])
    wait(lambda:(runtime/'native').exists())
    cli([
        'create-node adapter { factory.name = support.null-audio-sink node.name = elementary.eq.test '
        f'media.class = Audio/Sink device.id = {card_id} card.profile.device = 0 '
        'elementary.eq.profile = fixture-v1 node.cache-params = '+('true' if cache_probe else 'false')+' audio.channels = 2 audio.position = [ FL FR ] '
        'priority.session = 1000 object.linger = true }',
        'create-node adapter { factory.name = audiotestsrc node.name = elementary.eq.tone '
        f'device.id = {card_id} card.profile.device = 1 '
        'media.class = Audio/Source audio.channels = 2 audio.position = [ FL FR ] '
        'priority.session = 2000 object.linger = true }'
    ])
    wait(lambda:any(s['name']=='elementary.eq.test' for s in sinks()))
    sink = next(s for s in sinks() if s['name']=='elementary.eq.test')
    (evidence/'pulse-physical-fixture.json').write_text(json.dumps(sink, indent=2)+'\n')
    run(['pw-cli','info',str(card_id)])
    run(['pw-cli','enum-params',str(card_id),'EnumRoute'])
    run(['pw-cli','enum-params',str(card_id),'Route'])
    run(['pactl','-f','json','list','cards'])
    check('real_pulse_card_and_active_route', 'HARDWARE' in sink['flags'] and sink['active_port']=='fixture-speaker')
    nodes = objects()
    sink_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name')=='elementary.eq.test')
    tone_id = next(n['id'] for n in nodes if n.get('info',{}).get('props',{}).get('node.name')=='elementary.eq.tone')
    labels = ['bq_lowshelf', 'bq_peaking', 'bq_peaking', 'bq_peaking', 'bq_highshelf']
    graph_nodes = [dict(type='builtin', name=f'eos_eq_{i+1}', label=label, control=dict(Freq=freq, Q=.7, Gain=0.0))
                   for i,(label,freq) in enumerate(zip(labels,[100,250,1000,4000,10000]))]
    graph_nodes.append(dict(type='builtin', name='eos_eq_h', label='linear', control=dict(Mult=.25 if legacy else 1.0, Add=0.0)))
    links = [dict(output=f'eos_eq_{i}:Out', input=f'eos_eq_{i+1}:In') for i in range(1,5)]
    links.append(dict(output='eos_eq_5:Out', input='eos_eq_h:In'))
    graph = json.dumps(dict(nodes=graph_nodes, links=links))
    fmt = dict(mediaType='audio', mediaSubtype='raw', format='F32P', rate=48000, channels=2, position=['FL','FR'])
    cli([f'set-param {tone_id} PortConfig '+json.dumps(dict(direction='Output', mode='dsp', format=fmt)),
         f'set-param {sink_id} PortConfig '+json.dumps(dict(direction='Input', mode='dsp', format=fmt)),
         f'set-param {sink_id} Props '+json.dumps(dict(params=['audioconvert.filter-graph.0', graph])),
         f'set-param {sink_id} Props '+json.dumps(dict(channelVolumes=[.7,.35],mute=True))])
    for channel in ('FL','FR'): run(['pw-link', f'elementary.eq.tone:capture_{channel}', f'elementary.eq.test:playback_{channel}'])
    run(['pw-cli','enum-params',str(sink_id),'PropInfo'])
    run(['pw-cli','enum-params',str(sink_id),'Props'])
    run(['pactl','set-default-sink','elementary.eq.test'])
    run(['pactl','set-default-source','elementary.eq.tone'])
    owner = start('audio-owner', [str(base/'bridge-audio-owner')])
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
        check('cached_metadata_fails_closed', not last['available'] and not last['applied'])
        raise SystemExit(0)
    wait(lambda:receive().get('available') and last.get('applied'))
    if not legacy: check('initial_off_is_flat_unity', curve([0]*5,1))
    send('on')
    wait(lambda:receive().get('enabled') and last.get('applied') and curve([-1,-2,-3,-4,-5],.25))
    check('model_daemon_pulse_native_default_applied', True)
    subscriber = start('pulse-events', ['pactl','subscribe'], stdout=subprocess.PIPE, text=True)
    events=[]
    def read_events():
        for line in subscriber.stdout: events.append(line.strip())
    threading.Thread(target=read_events, daemon=True).start()
    time.sleep(.2)
    run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-7.0]))])
    if not legacy:
        wait(lambda:receive().get('error') and curve([-7,-2,-3,-4,-5],.25))
    for value in ('0','1','0','1'):
        run(['pw-cli','set-param',str(sink_id),'Props','{ mute = '+('true' if value=='1' else 'false')+' }']); time.sleep(.15)
    wait(lambda:any('sink #' in e for e in events))
    time.sleep(2)
    receive()
    (evidence/'foreign-after-pulse-events.json').write_text(json.dumps(dict(status=last, controls=props(), events=events),indent=2)+'\n')
    if legacy:
        check('legacy_reproduces_foreign_gain_overwrite', curve([-1,-2,-3,-4,-5],.25))
    else:
        check('foreign_gain_survives_real_sink_events', curve([-7,-2,-3,-4,-5],.25))
        check('native_failed_audit_survives_rediscovery', not last['available'] and not last['applied'] and bool(last['error']))
        send('on'); send('gain'); time.sleep(.3)
        check('failed_enable_and_gain_fail_closed', curve([-7,-2,-3,-4,-5],.25))
        send('off')
        wait(lambda:not receive().get('enabled',True) and last.get('applied') and curve([0]*5,1))
        wait(lambda:receive().get('gtk_switch_sensitive') and last.get('aec_available'))
        send('aec-on')
        wait(lambda:receive().get('aec_enabled') and not last.get('aec_busy') and last.get('applied') and last.get('gtk_switch_sensitive'))
        send('gtk-toggle')
        wait(lambda:receive().get('gtk_on') and last.get('applied') and curve([-1,-2,-3,-4,-5],.25))
        check('real_gtk_enable_with_owned_aec', last['aec_enabled'] and not last['aec_error'])
        for band in range(5): send(f'gtk-gain {band} {-7+band}')
        wait(lambda:receive().get('applied') and curve([-7,-6,-5,-4,-3],.25))
        check('all_five_real_gtk_sliders_reach_native_controls', last['aec_enabled'])
        send('gtk-flat')
        wait(lambda:receive().get('preset')=='flat' and last.get('applied') and curve([0]*5,1))
        check('real_gtk_flat_unity_with_owned_aec', last['aec_enabled'])
        send('gtk-reset')
        wait(lambda:receive().get('preset')=='device-default' and last.get('applied') and curve([-1,-2,-3,-4,-5],.25))
        check('real_gtk_reset_with_owned_aec', last['aec_enabled'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        wait(lambda:receive().get('error') and last.get('gtk_switch_sensitive') and not last.get('gtk_bands_sensitive'))
        send('gtk-toggle')
        wait(lambda:not receive().get('gtk_on',True) and last.get('applied') and curve([0]*5,1))
        check('real_gtk_failed_off_recovers_unity_with_owned_aec', last['aec_enabled'])
        send('aec-off')
        wait(lambda:not receive().get('aec_enabled',True) and not last.get('aec_busy'))
        check('owned_aec_disables_without_changing_eq_controls', curve([0]*5,1))
        check('failed_off_withdraws_preference_and_bypasses', True)
        send('on'); wait(lambda:receive().get('enabled') and last.get('applied') and curve([-1,-2,-3,-4,-5],.25))
        send('flat'); wait(lambda:receive().get('preset')=='flat' and last.get('applied') and curve([0]*5,1))
        check('enabled_flat_has_unity_headroom', True)
        send('default'); wait(lambda:receive().get('applied') and curve([-1,-2,-3,-4,-5],.25))
        send('gain'); wait(lambda:receive().get('preset')=='custom' and last.get('applied') and curve([-6,-2,-3,-4,-5],.25))
        check('explicit_custom_applies_fixed_profile_headroom', True)
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 1 device = 0 }'])
        wait(lambda:receive().get('route')=='fixture-headphones' and curve([0]*5,1))
        check('observed_route_change_bypasses', not last['available'])
        run(['pw-cli','set-param',str(card_id),'Route','{ index = 0 device = 0 }'])
        wait(lambda:receive().get('route')=='fixture-speaker' and last.get('applied') and curve([-6,-2,-3,-4,-5],.25))
        check('speaker_route_return_reapplies_preferences', True)
        linked(False)
        wait(lambda:not receive().get('applied'))
        time.sleep(1.2)
        linked(True)
        wait(lambda:receive().get('applied') and curve([-6,-2,-3,-4,-5],.25))
        check('unchanged_idle_resume_confirms_read_only', True)
        for control, value, expected, headroom in (
                ('eos_eq_1:Gain', -7., [-7,-2,-3,-4,-5], .25),
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
            wait(lambda:not receive().get('enabled',True) and last.get('applied') and curve([0]*5,1))
            send('on')
            wait(lambda:receive().get('enabled') and last.get('applied') and curve([-6,-2,-3,-4,-5],.25))
        clients = native_clients()
        (evidence/'clients.json').write_text(json.dumps([o for o in objects() if o['type']=='PipeWire:Interface:Client'],indent=2)+'\n')
        check('exactly_one_native_client', len(clients)==1)
        run(['pw-cli','destroy',str(clients[0]['id'])])
        wait(lambda:receive().get('error') and not last['applied'])
        wait(lambda:receive().get('applied') and len(native_clients())==1)
        check('native_disconnect_reconnect_same_owner', owner.poll() is None and curve([-6,-2,-3,-4,-5],.25))
        # A disconnected client must not regain write permission for its old request.
        run(['pw-cli','destroy',str(native_clients()[0]['id'])])
        wait(lambda:receive().get('error') and not last['applied'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['eos_eq_1:Gain',-8.]))])
        time.sleep(3.5)
        receive()
        check('foreign_gain_survives_reconnect', bool(last['error']) and not last['applied'] and curve([-8,-2,-3,-4,-5],.25))
        send('off')
        wait(lambda:not receive().get('enabled',True) and last.get('applied') and curve([0]*5,1))
        send('invalid-gains')
        time.sleep(.3)
        check('nonfinite_out_of_range_and_invalid_band_refused', curve([0]*5,1))
        linked(False)
        wait(lambda:not receive().get('applied'))
        send('on')
        wait(lambda:receive().get('enabled') and not last.get('busy'))
        check('explicit_idle_request_waits_for_running_node', not last['applied'])
        send('off')
        wait(lambda:not receive().get('enabled',True) and not last.get('busy'))
        linked(True)
        wait(lambda:receive().get('applied') and curve([0]*5,1))
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
        check('deadline_cancellation_reconnects_without_old_write', curve([0]*5,1))
        run(['pw-cli','set-param',str(sink_id),'Props','{ mute = true }'])
        run(['pw-cli','set-param',str(sink_id),'Props',json.dumps(dict(params=['audioconvert.filter-graph.1',graph]))])
        wait(lambda:receive().get('error') and not last['applied'])
        check('duplicate_reserved_namespace_fails_closed', not last['available'])
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
        wait(lambda:any(s['name']=='elementary.eq.test' for s in sinks()))
        replacement = next(o for o in objects() if o.get('info',{}).get('props',{}).get('node.name')=='elementary.eq.test')
        sink_id = replacement['id']
        graph_nodes[0]['control']['Freq']=101.
        bad_graph=json.dumps(dict(nodes=graph_nodes,links=links))
        cli([f'set-param {sink_id} PortConfig '+json.dumps(dict(direction='Input',mode='dsp',format=fmt)),
             f'set-param {sink_id} Props '+json.dumps(dict(params=['audioconvert.filter-graph.0',bad_graph]))])
        run(['pactl','set-default-sink','elementary.eq.test'])
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
            p.send_signal(signal.SIGCONT)
            p.terminate()
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
    for log in logs: log.close()
    (evidence/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    (evidence/'observations.json').write_text(json.dumps(observations,indent=2)+'\n')
    (evidence/'checks.json').write_text(json.dumps(dict(checks=checks,failure=failure,runtime=str(runtime)),indent=2)+'\n')
    shutil.rmtree(runtime)
print(json.dumps(checks))
