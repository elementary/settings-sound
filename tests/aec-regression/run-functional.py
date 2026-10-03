#!/usr/bin/env python3
"""Private native Pulse/PipeWire tests; run inside vale-sound-sdk, never on host.
Production code is exercised by echo-client, compiled from EchoCancellation.vala.
The documented pactl client supplies fixtures and independently inspects state.
"""
import json, os, pathlib, queue, select as fd_select, signal, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = pathlib.Path(__file__).resolve().parent
assert ROOT.joinpath('src/EchoCancellation.vala').exists()
assert not pathlib.Path('/dev/snd').exists(), 'Refuse to run with hardware audio accessible'
KIND = sys.argv[1]
UI_ONLY = '--ui-only' in sys.argv
FAULTS = '--faults' in sys.argv
ROUTES = '--routes' in sys.argv
DOWNSTREAM = '--downstream' in sys.argv or ROUTES
RUN_NAME = KIND + ('-downstream' if DOWNSTREAM else '') + ('-routes' if ROUTES else '') + ('-ui-only' if UI_ONLY else '-faults' if FAULTS else '')
assert KIND in ('pulse', 'pipewire', 'pulse-denied')
TEMP = pathlib.Path(tempfile.mkdtemp(prefix='vale-sound-' + KIND + '-'))
TEMP.chmod(0o700)
ENV = dict(os.environ, XDG_RUNTIME_DIR=str(TEMP), XDG_CONFIG_HOME=str(TEMP/'user-config'),
           XDG_STATE_HOME=str(TEMP/'state'), XDG_CACHE_HOME=str(TEMP/'cache'),
           PULSE_SERVER='unix:' + str(TEMP/'native'), GSETTINGS_SCHEMA_DIR=str(ROOT/'tests/schemas'),
           GSETTINGS_BACKEND='keyfile', ALSA_CONFIG_PATH=str(TEMP/'asound.conf'))
ENV.pop('DBUS_SESSION_BUS_ADDRESS', None)
ENV.pop('DISPLAY', None)
ENV.pop('WAYLAND_DISPLAY', None)
TEMP.joinpath('asound.conf').write_text('pcm.!default { type null }\n')
PROCESSES = []
LOGS = []
RESULTS = []

def launch(args, **kwargs):
    p = subprocess.Popen(args, env=ENV, **kwargs)
    PROCESSES.append(p)
    return p

def daemon(name, args):
    f = open(TEMP/(name+'.log'), 'w'); LOGS.append(f)
    return launch(args, stdout=f, stderr=f)

def pactl(*args, check=True):
    p = subprocess.run(['pactl', *map(str,args)], env=ENV, text=True, capture_output=True, timeout=8)
    if check and p.returncode: raise AssertionError((args,p.stderr))
    return p.stdout.strip()

def items(kind): return json.loads(pactl('-f','json','list',kind))
def modules():
    return [fields for line in pactl('list','short','modules').splitlines() if len(fields := line.split('\t',3)) >= 3 and fields[0].isdigit()]
def owned(): return [x for x in modules() if x[1]=='module-echo-cancel' and 'device.echo_cancel.owner=io.elementary.settings.sound' in x[2]]
def eventually(fn, limit=8):
    end=time.monotonic()+limit
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Timed out: '+repr(fn))

def defaults():
    text=pactl('info')
    return tuple(next(line.split(': ',1)[1] for line in text.splitlines() if line.startswith('Default '+kind+':')) for kind in ('Source','Sink'))

def select(source='physical_input', sink='physical_output'):
    pactl('set-default-source',source);pactl('set-default-sink',sink)
    eventually(lambda:defaults()==(source,sink))

def volumes():
    out={}
    for kind,name in [('sources','physical_input'),('sinks','physical_output')]:
        x=next(x for x in items(kind) if x['name']==name)
        out[name]=(tuple(v['value'] for v in x['volume'].values()),x['mute'])
    return out

class Client:
    def __init__(self):
        self.errors=open(TEMP/('client-'+str(len(PROCESSES))+'.log'),'w');LOGS.append(self.errors)
        self.p=launch([str(FIXTURE / 'echo-client')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,text=True)
        self.q=queue.Queue(); self.last={}
        def read():
            for line in self.p.stdout:
                self.q.put(json.loads(line))
        threading.Thread(target=read,daemon=True).start()
    def command(self,command):
        while not self.q.empty():self.last=self.q.get()
        self.p.stdin.write(command+'\n');self.p.stdin.flush()
    def wait(self,fn,limit=10):
        end=time.monotonic()+limit;stable=None
        while time.monotonic()<end:
            try:self.last=self.q.get(timeout=.2)
            except queue.Empty:
                assert self.p.poll() is None, 'Native client exited'
                continue
            if fn(self.last) and not self.last['busy']:
                stable=stable or time.monotonic()
                if time.monotonic()-stable>.15:return self.last
            else:stable=None
        raise AssertionError('Controller timeout: '+repr(self.last))
    def stop(self):
        if self.p.poll() is None:self.command('quit');self.p.wait(timeout=6)

def ui_smoke():
    ui=subprocess.run(['xvfb-run','-a',str(FIXTURE / 'ui-client-detached') if DOWNSTREAM else str(FIXTURE / 'ui-client')],env=ENV,
                      capture_output=True,text=True,timeout=15)
    FIXTURE.joinpath(RUN_NAME+'-ui.log').write_text(ui.stdout+ui.stderr)
    assert ui.returncode==0, (ui.stdout,ui.stderr)
    assert not owned()
    ok('real InputPanel GTK switch enables/disables through PulseAudioManager without notification feedback')

def ok(message):
    RESULTS.append(message);print('PASS',KIND,message,flush=True)

def native_streams(source, sink, pinned):
    p=launch([str(FIXTURE / 'stream-client'),source,sink,pinned if isinstance(pinned,str) else 'pinned' if pinned else 'active'],
             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    assert fd_select.select([p.stdout],[],[],6)[0], 'Native stream connection timeout'
    line=p.stdout.readline()
    assert line, p.stderr.read()
    output,input_=map(int,line.split())
    return [(p,'sink-inputs',output),(p,'source-outputs',input_)]

def stream_target(kind,index):
    return next(x['sink' if kind=='sink-inputs' else 'source'] for x in items(kind) if x['index']==index)

def run():
    bus=subprocess.check_output(['dbus-daemon','--session','--fork','--print-address=1','--print-pid=1'],env=ENV,text=True).splitlines()
    ENV['DBUS_SESSION_BUS_ADDRESS']=bus[0];global BUS_PID;BUS_PID=int(bus[1])
    if KIND.startswith('pulse'):
        commands=['load-module module-native-protocol-unix socket='+str(TEMP/'native')+' auth-anonymous=1']
        for suffix in ('','2'):
            commands+=['load-module module-alsa-sink device=default sink_name=physical_output'+suffix+' tsched=0',
                       'load-module module-alsa-source device=default source_name=physical_input'+suffix+' tsched=0'+(' source_properties=device.echo_cancel.policy=vale-detached-camera' if ROUTES and suffix=='' else '')]
        commands+=['set-default-sink physical_output','set-default-source physical_input']
        TEMP.joinpath('test.pa').write_text('\n'.join(commands)+'\n')
        server=daemon('pulse',['pulseaudio','-nF',str(TEMP/'test.pa'),'--daemonize=no','--exit-idle-time=-1','--use-pid-file=no'] + (['--disallow-module-loading=yes'] if KIND=='pulse-denied' else []))
    else:
        config=TEMP/'config';(config/'pipewire.conf.d').mkdir(parents=True)
        ENV['PIPEWIRE_CONFIG_DIR']=str(config)
        config.joinpath('pipewire.conf').write_text(pathlib.Path('/usr/share/pipewire/pipewire.conf').read_text())
        config.joinpath('client.conf').write_text(pathlib.Path('/usr/share/pipewire/client.conf').read_text())
        config.joinpath('pipewire-pulse.conf').write_text(pathlib.Path('/usr/share/pipewire/pipewire-pulse.conf').read_text().replace('unix:native','unix:'+str(TEMP/'native')))
        objects=[]
        for suffix in ('','2'):
            for direction,media in [('sink','Sink'),('source','Source')]:
                name='physical_'+('output' if direction=='sink' else 'input')+suffix
                objects.append('''{ factory = adapter args = {
                    factory.name = api.alsa.pcm.%s node.name = %s node.description = "%s"
                    priority.session = %s media.class = Audio/%s device.api = alsa device.class = sound api.alsa.path = default
                    api.alsa.period-size = 480 api.alsa.headroom = 0 api.alsa.disable-mmap = true
                    audio.rate = 48000 audio.channels = 2 audio.position = [ FL FR ]
                } }'''%(direction,name,name,2000 if direction=='source' else 1000,media)+('' if not (ROUTES and direction=='source' and suffix=='') else ''))
        if ROUTES:
            objects[1]=objects[1].replace('node.description =', 'device.echo_cancel.policy = vale-detached-camera node.hidden = true node.description =')
        config.joinpath('pipewire.conf.d/10-synthetic.conf').write_text('context.objects = [\n'+'\n'.join(objects)+'\n]\n')
        core=daemon('pipewire',['pipewire'])
        eventually(lambda:(TEMP/'pipewire-0').exists())
        server=daemon('pulse',['pipewire-pulse']);wireplumber=daemon('wireplumber',['wireplumber'])
    eventually(lambda:(TEMP/'native').exists())
    eventually(lambda:len(items('sinks'))>=2)
    select()
    if FAULTS or ROUTES:
        if ROUTES:TEMP.joinpath('active-route').write_text('analog-input-internal-mic')
        TEMP.joinpath('pulse-client.conf').write_text('enable-shm=no\n')
        ENV['PULSE_CLIENTCONFIG']=str(TEMP/'pulse-client.conf')
        daemon('fault-proxy',['python3',str(FIXTURE / 'native-fault-proxy.py'),str(TEMP/'native'),str(TEMP/'fault-native')])
        eventually(lambda:(TEMP/'fault-native').exists())
        ENV['PULSE_SERVER']='unix:'+str(TEMP/'fault-native')
    owner=daemon('audio-owner',[str(FIXTURE / 'audio-owner-detached') if DOWNSTREAM else str(FIXTURE / ('audio-owner-baseline' if os.environ.get('AEC_BASELINE') else 'audio-owner'))])
    ENV['PULSE_SERVER']='unix:'+str(TEMP/'native')
    client=Client();client.wait(lambda x:not x['available'] if ROUTES else x['available'])
    api=subprocess.check_output(['gdbus','introspect','--session','--dest','io.elementary.settings-daemon',
        '--object-path','/io/elementary/settings_daemon','--xml'],env=ENV,text=True)
    FIXTURE.joinpath(KIND+'-audio-api.xml').write_text(api)
    assert '<method name="GetStatus">' in api and '<method name="Start">' not in api

    if not os.environ.get("AEC_BASELINE"):
        eq = subprocess.check_output(['gdbus','call','--session','--dest','io.elementary.settings-daemon',
            '--object-path','/io/elementary/settings_daemon','--method','io.elementary.settings_daemon.Audio.GetEqualizerStatus'],env=ENV,text=True)
        assert eq.startswith('((false,'), eq
        ok('EQ unavailable without a root profile; existing AEC API remains present')

    if ROUTES:
        physical=next(x for x in items('sources') if x['name']=='physical_input')
        assert physical['properties']['device.echo_cancel.policy']=='vale-detached-camera'
        FIXTURE.joinpath(RUN_NAME+'-native-marker.json').write_text(json.dumps(physical,indent=2)+'\n')
        if KIND=='pipewire':assert physical['properties']['node.hidden']=='true'
        ENV['PULSE_SERVER']='unix:'+str(TEMP/'fault-native')
        ui_log=open(TEMP/'input-list-errors.log','w');LOGS.append(ui_log)
        ui=launch(['xvfb-run','-a',str(FIXTURE / 'input-list-client')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=ui_log,text=True)
        ENV['PULSE_SERVER']='unix:'+str(TEMP/'native')
        ui_queue=queue.Queue();ui_samples=[]
        def ui_read():
            for line in ui.stdout:
                value=json.loads(line);ui_samples.append(value);ui_queue.put(value)
        threading.Thread(target=ui_read,daemon=True).start()
        def ui_wait(ports):
            deadline=time.monotonic()+15;stable=None
            while time.monotonic()<deadline:
                try:value=ui_queue.get(timeout=.2)
                except queue.Empty:
                    assert ui.poll() is None,'Native GTK input list exited';continue
                if sorted(value['ports'])==sorted(ports):
                    stable=stable or time.monotonic()
                    if time.monotonic()-stable>.3:return value
                else:stable=None
            raise AssertionError(('Input list timeout',ports,ui_samples[-1] if ui_samples else None))
        ui_wait(['usb-input'])
        ok('real Sound input list hides marked internal port; independent USB-style input remains visible')
        before=volumes()
        def desired():return subprocess.check_output(['gsettings','get','io.elementary.settings-daemon.audio','echo-cancellation'],env=ENV,text=True).strip()
        def route(name):
            TEMP.joinpath('active-route').write_text(name)
            # Trigger genuine SOURCE changes on the private synthetic source.
            # Port metadata is fixture-injected; no actual HDA jack is exercised.
            mute=next(x for x in items('sources') if x['name']=='physical_input')['mute']
            pactl('set-source-mute','physical_input','0' if mute else '1')
            pactl('set-source-mute','physical_input','1' if mute else '0')
        client.command('enable');client.wait(lambda x:not x['enabled'] and not x['available'])
        assert desired()=='true' and not owned()
        ok('marked internal active port refused; saved enabled preference retained')
        for name in ('','analog-input-linein'):
            route(name);client.wait(lambda x:not x['enabled'] and not x['available'])
            assert desired()=='true' and not owned()
        ok('marked missing and unrecognized active ports refused')
        TEMP.joinpath('headset').touch();route('analog-input-mic');client.wait(lambda x:x['enabled'])
        ui_wait(['analog-input-mic','usb-input'])
        ok('same marked HDA node exposes external headset row after port availability/switch')
        assert owned() and 'source_master="physical_input"' in owned()[0][2]
        streams=native_streams('elementary_echo_cancel_source','elementary_echo_cancel_sink',False)
        TEMP.joinpath('headset').unlink();route('analog-input-internal-mic');client.wait(lambda x:not x['enabled'] and not x['available'])
        assert not owned() and desired()=='true'
        ui_wait(['usb-input'])
        ok('headset removal hides unavailable shared-node input; USB list survives')
        for p,kind,index in streams:
            expected=next(x['index'] for x in items('sinks' if kind=='sink-inputs' else 'sources') if x['name']==('physical_output' if kind=='sink-inputs' else 'physical_input'))
            assert stream_target(kind,index)==expected
        for p in {entry[0] for entry in streams}:p.stdin.write('quit\n');p.stdin.flush();p.wait(timeout=4)
        ok('external route eligible; external-to-internal change releases AEC and rescues movable streams')
        TEMP.joinpath('headset').touch();route('analog-input-mic');client.wait(lambda x:x['enabled'])
        ui_wait(['analog-input-mic','usb-input'])
        ok('internal-to-external route change reapplies retained enabled preference')
        select('physical_input2');client.wait(lambda x:x['enabled'] and x['source']=='physical_input2')
        assert 'source_master="physical_input2"' in owned()[0][2]
        client.command('disable');client.wait(lambda x:not x['enabled']);assert not owned()
        assert before==volumes()
        ok('unmarked independent USB-style capture remains eligible; physical gain/mute unchanged')
        TEMP.joinpath('headset').unlink()
        def replace_source(marked):
            if KIND=='pulse':
                old=next(x for x in items('sources') if x['name']=='physical_input')
                pactl('unload-module',old['owner_module'])
                args=['device=default','source_name=physical_input','tsched=0']
                if marked:args.append('source_properties=device.echo_cancel.policy=vale-detached-camera')
                pactl('load-module','module-alsa-source',*args)
            else:
                dump=json.loads(subprocess.check_output(['pw-dump'],env=ENV,text=True))
                node=next(x['id'] for x in dump if x.get('info',{}).get('props',{}).get('node.name')=='physical_input')
                subprocess.run(['pw-cli','destroy',str(node)],env=ENV,check=True,capture_output=True,timeout=5)
                props='{ factory.name=api.alsa.pcm.source node.name=physical_input node.description=physical_input media.class=Audio/Source device.api=alsa device.class=sound api.alsa.path=default api.alsa.period-size=480 api.alsa.headroom=0 api.alsa.disable-mmap=true audio.rate=48000 audio.channels=2 audio.position=[ FL FR ] object.linger=true '+('device.echo_cancel.policy=vale-detached-camera node.hidden=true ' if marked else '')+'}'
                subprocess.run(['pw-cli','create-node','adapter',props],env=ENV,check=True,capture_output=True,timeout=5)
            eventually(lambda:any(x['name']=='physical_input' for x in items('sources')))
        replace_source(False)
        route('analog-input-internal-mic');select('physical_input')
        client.wait(lambda x:x['available'])
        ui_wait(['analog-input-internal-mic','usb-input'])
        client.command('enable');client.wait(lambda x:x['enabled'])
        ok('native policy-marker change restores internal Sound row and AEC eligibility when camera policy clears')
        client.command('disable');client.wait(lambda x:not x['enabled'])
        replace_source(True)
        client.command('enable')
        route('analog-input-internal-mic')
        client.wait(lambda x:not x['enabled'] and not x['available'])
        ui_wait(['usb-input']);assert desired()=='true' and not owned()
        client.command('disable');client.wait(lambda x:not x['enabled'])
        ok('native marker reattachment hides internal row and releases AEC while keeping saved preference')
        ui.stdin.write('quit\n');ui.stdin.flush();ui.wait(timeout=5)
        FIXTURE.joinpath(RUN_NAME+'-input-list.json').write_text(json.dumps(ui_samples,indent=2)+'\n')
        return
    if FAULTS:
        for direction,mode,kind in [('source','capture-pinned','source-outputs'),('sink','playback-pinned','sink-inputs')]:
            client.command('enable');client.wait(lambda x:x['enabled'])
            module=owned()[0][0]
            streams=native_streams('elementary_echo_cancel_source','elementary_echo_cancel_sink',mode)
            pinned=next((p,k,idx) for p,k,idx in streams if k==kind)
            target=stream_target(kind,pinned[2]);time.sleep(.3)
            (TEMP/('fail-'+direction)).touch();client.command('disable')
            client.wait(lambda x:bool(x['error']) or not x['enabled'])
            assert owned() and owned()[0][0]==module, 'query failure unloaded protected module'
            assert pinned[0].poll() is None and stream_target(kind,pinned[2])==target, 'query failure destroyed DONT_MOVE stream'
            ok('native negative '+direction+' query: unknown ownership retains module and single-direction DONT_MOVE stream')
            pinned[0].stdin.write('quit\n');pinned[0].stdin.flush();pinned[0].wait(timeout=5)
            client.wait(lambda x:not x['enabled']);assert not owned()
        client.command('enable');client.wait(lambda x:x['enabled'] and x['source']=='physical_input')
        client.command('disable');client.wait(lambda x:not x['enabled'] and x['source']=='' and x['sink']=='')
        foreign=pactl('load-module','module-echo-cancel','source_master=physical_input sink_master=physical_output source_name=elementary_echo_cancel_source sink_name=elementary_echo_cancel_sink aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=0"')
        pactl('set-default-source','elementary_echo_cancel_source');pactl('set-default-sink','elementary_echo_cancel_sink')
        client.wait(lambda x:not x['available'] and x['source']=='' and x['sink']=='')
        assert any(x[0]==foreign for x in modules()) and not owned()
        ok('released ownership then foreign reserved defaults: no stale physical aliases or foreign module unload')
        pactl('unload-module',foreign);select();client.wait(lambda x:x['available'])
        (TEMP/'delay-load').touch();(TEMP/'delay-discovery').touch()
        before=volumes();client.command('enable')
        client.wait(lambda x:not x['enabled'] and bool(x['error']),limit=12)
        def fault_events():
            path=TEMP/'fault-events.jsonl'
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        eventually(lambda:any(e['event']=='late-module-created' for e in fault_events()),limit=8)
        eventually(lambda:not owned(),limit=8)
        client.wait(lambda x:not x['enabled'])
        assert defaults()==('physical_input','physical_output') and volumes()==before
        events=fault_events();load=next(e for e in events if e['event']=='load-pending');created=next(e for e in events if e['event']=='late-module-created')
        assert created['time']-load['time']>=12.5 and any(e['event']=='discovery-pending' for e in events)
        FIXTURE.joinpath(RUN_NAME+'-events.json').write_text(json.dumps(events,indent=2)+'\n')
        ok('native pending load and discovery timeouts: later actual module creation adopted/released with preference disabled')
        client.command('enable');client.wait(lambda x:x['enabled'])
        surviving=owned()[0][0];owner.terminate();owner.wait(timeout=5)
        client.wait(lambda x:not x['available'] and x['source']=='' and x['sink']=='')
        (TEMP/'delay-initial-discovery').touch()
        ENV['PULSE_SERVER']='unix:'+str(TEMP/'fault-native')
        owner=daemon('initial-discovery-owner',[str(FIXTURE / 'audio-owner-detached') if DOWNSTREAM else str(FIXTURE / ('audio-owner-baseline' if os.environ.get('AEC_BASELINE') else 'audio-owner'))])
        ENV['PULSE_SERVER']='unix:'+str(TEMP/'native')
        client.wait(lambda x:not x['available'] and bool(x['error']),limit=8)
        client.wait(lambda x:x['enabled'],limit=12)
        assert len(owned())==1 and owned()[0][0]==surviving
        ok('initial module discovery timeout: later bounded retry adopts surviving exact module without duplication')
        client.command('disable');client.wait(lambda x:not x['enabled']);assert not owned()
        client.stop();return
    if UI_ONLY:
        client.stop();ui_smoke();return
    if KIND=='pulse-denied':
        before=volumes()
        client.command('enable');client.wait(lambda x:'not available' in x['error'])
        assert not owned() and defaults()==('physical_input','physical_output') and volumes()==before
        ok('native load-module rejection: error, preference rollback, no default/volume changes')
        client.stop();return
    pactl('set-source-volume','physical_input','44%','66%');pactl('set-sink-volume','physical_output','36%','52%')
    pactl('set-source-mute','physical_input','1');pactl('set-sink-mute','physical_output','1')
    before=volumes()
    pinned=native_streams('physical_input','physical_output',True)
    targets=[stream_target(kind,idx) for _,kind,idx in pinned]
    client.command('enable');client.wait(lambda x:x['enabled'])
    assert defaults()==('elementary_echo_cancel_source','elementary_echo_cancel_sink')
    assert len(owned())==1 and volumes()==before
    for (_,kind,idx),target in zip(pinned,targets):assert stream_target(kind,idx)==target
    ok('enable: correct physical masters, both defaults, asymmetric native volume/mute, pinned streams untouched')
    filtered=native_streams('elementary_echo_cancel_source','elementary_echo_cancel_sink',False)
    module=int(owned()[0][0])
    source_index=next(x['index'] for x in items('sources') if x['name']=='physical_input')
    sink_index=next(x['index'] for x in items('sinks') if x['name']=='physical_output')
    try:
        eventually(lambda:any(int(x['owner_module'] or -1)==module and x['source']==source_index for x in items('source-outputs')))
    except AssertionError:
        FIXTURE.joinpath(KIND+'-reference-debug.json').write_text(json.dumps({'sources':items('source-outputs'),'sinks':items('sink-inputs')},indent=2))
        raise
    eventually(lambda:any(int(x['owner_module'] or -1)==module and x['sink']==sink_index for x in items('sink-inputs')))
    FIXTURE.joinpath(KIND+'-native-references.json').write_text(json.dumps({
        'module':module,'physical_source_index':source_index,'physical_sink_index':sink_index,
        'capture':[x for x in items('source-outputs') if int(x['owner_module'] or -1)==module],
        'playback':[x for x in items('sink-inputs') if int(x['owner_module'] or -1)==module]},indent=2)+'\n')
    ok('native reference streams actually attach to the selected physical source and sink')
    client.command('disable');client.wait(lambda x:not x['enabled'])
    assert not owned() and defaults()==('physical_input','physical_output') and volumes()==before
    for p,kind,idx in filtered:
        assert p.poll() is None
        expected=next(x['index'] for x in items('sinks' if kind=='sink-inputs' else 'sources') if x['name']==('physical_output' if kind=='sink-inputs' else 'physical_input'))
        assert stream_target(kind,idx)==expected
    ok('disable: owned streams rescued, physical defaults/volume/mute restored, no module left')
    for p in {p for p,_,_ in filtered+pinned}:p.stdin.write("quit\n");p.stdin.flush();p.wait(timeout=5)
    client.command('enable');client.wait(lambda x:x['enabled'])
    own_pinned=native_streams('elementary_echo_cancel_source','elementary_echo_cancel_sink',True)
    own_targets=[stream_target(kind,idx) for _,kind,idx in own_pinned]
    client.command('disable');status=client.wait(lambda x:(x['enabled'] and bool(x['error'])) or not x['enabled'])
    for (p,kind,idx),target in zip(own_pinned,own_targets):
        assert p.poll() is None
        if status['enabled']:assert stream_target(kind,idx)==target and owned()
    for p in {p for p,_,_ in own_pinned}:p.stdin.write('quit\n');p.stdin.flush();p.wait(timeout=5)
    client.command('disable');client.wait(lambda x:not x['enabled']);assert not owned()
    ok('DONT_MOVE on owned endpoints: migration refusal retains filter and streams; retry after client closes')
    client.command('enable');client.wait(lambda x:x['enabled']);old=owned()[0][0]
    client.stop();client=Client();client.wait(lambda x:x['enabled'])
    assert len(owned())==1 and owned()[0][0]==old
    ok('close/reopen: saved preference and exact owned-module adoption, no duplicate')
    pactl('set-source-volume','physical_input','33%','55%');pactl('set-source-mute','physical_input','0')
    changed=volumes();client.command('disable');client.wait(lambda x:not x['enabled']);assert volumes()==changed
    ok('user volume/mute changes while enabled survive disabling')
    collision=pactl('load-module','module-null-sink','sink_name=elementary_echo_cancel_sink')
    select();client.command('enable');client.wait(lambda x:'already in use' in x['error'])
    assert not owned() and any(x[0]==collision for x in modules())
    pactl('unload-module',collision);select()
    ok('namespace collision: foreign endpoint untouched, error shown, preference rolled back')
    client.command('disable');client.wait(lambda x:not x['enabled'])
    pactl('set-default-source','physical_output.monitor');eventually(lambda:defaults()[0]=='physical_output.monitor')
    client.command('enable');client.wait(lambda x:not x['available'])
    assert not owned();ok('monitor source rejected')
    client.command('disable');select();client.wait(lambda x:x['available'])
    foreign=pactl('load-module','module-echo-cancel','source_master=physical_input sink_master=physical_output source_name=foreign_echo_source sink_name=foreign_echo_sink aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=0"')
    pactl('set-default-source','foreign_echo_source');pactl('set-default-sink','physical_output')
    eventually(lambda:defaults()==('foreign_echo_source','physical_output'))
    client.command('enable');client.wait(lambda x:not x['available']);assert not owned() and any(x[0]==foreign for x in modules())
    client.command('disable');pactl('unload-module',foreign);select()
    ok('processed source rejected; third-party echo module never adopted/unloaded')
    client.command('enable');client.wait(lambda x:x['enabled'])
    pactl('set-default-source','physical_input2');pactl('set-default-sink','physical_output2')
    client.wait(lambda x:x['enabled'] and x['source']=='physical_input2' and x['sink']=='physical_output2')
    assert len(owned())==1
    ok('external input/output selection rebinds physical references without recursive masters')
    # Settings/control process is absent throughout restart recovery.
    client.stop()
    owner.terminate();owner.wait(timeout=5)
    old=owned()[0][0]
    owner=daemon('audio-owner-restarted',[str(FIXTURE / 'audio-owner-detached') if DOWNSTREAM else str(FIXTURE / ('audio-owner-baseline' if os.environ.get('AEC_BASELINE') else 'audio-owner'))])
    eventually(lambda:len(owned())==1 and owned()[0][0]==old)
    time.sleep(.5)
    assert defaults()==('elementary_echo_cancel_source','elementary_echo_cancel_sink')
    ok('session owner restart with Sound closed: exact module adoption without duplication')
    # Destroy the server runtime, including the echo module; the surviving
    # production owner must reconnect and apply its stored preference.
    if KIND=='pulse':
        server.terminate();server.wait(timeout=5)
        server=daemon('pulse-restarted',['pulseaudio','-nF',str(TEMP/'test.pa'),'--daemonize=no','--exit-idle-time=-1','--use-pid-file=no'])
    else:
        for proc in (wireplumber,server,core):
            proc.terminate();proc.wait(timeout=5)
        core=daemon('pipewire-restarted',['pipewire'])
        eventually(lambda:(TEMP/'pipewire-0').exists())
        server=daemon('pulse-restarted',['pipewire-pulse'])
        wireplumber=daemon('wireplumber-restarted',['wireplumber'])
    eventually(lambda:(TEMP/'native').exists())
    eventually(lambda:len(owned())==1 and defaults()==('elementary_echo_cancel_source','elementary_echo_cancel_sink'),limit=15)
    ok('audio server restart with Sound closed: saved preference reapplied by surviving session owner')
    owner.terminate();owner.wait(timeout=5)
    pactl('unload-module',owned()[0][0]);select()
    owner=daemon('audio-owner-fresh-session',[str(FIXTURE / 'audio-owner-detached') if DOWNSTREAM else str(FIXTURE / ('audio-owner-baseline' if os.environ.get('AEC_BASELINE') else 'audio-owner'))])
    eventually(lambda:len(owned())==1 and defaults()==('elementary_echo_cancel_source','elementary_echo_cancel_sink'),limit=15)
    ok('fresh session owner with Sound closed: stored preference loads missing module and routes defaults')
    client=Client();client.wait(lambda x:x['enabled'])
    # Rebind to the second pair again for the original hot-removal invariant.
    pactl('set-default-source','physical_input2');pactl('set-default-sink','physical_output2')
    client.wait(lambda x:x['enabled'] and x['source']=='physical_input2' and x['sink']=='physical_output2')
    # Remove current capture hardware entirely, using the native server tools.
    if KIND=='pulse':
        source=next(x for x in items('sources') if x['name']=='physical_input2')
        pactl('unload-module',source['owner_module'])
    else:
        dump=json.loads(subprocess.check_output(['pw-dump'],env=ENV,text=True))
        node=next(x['id'] for x in dump if x.get('info',{}).get('props',{}).get('node.name')=='physical_input2')
        subprocess.run(['pw-cli','destroy',str(node)],env=ENV,check=True,capture_output=True,timeout=5)
    client.wait(lambda x:x['enabled'] and x['source']=='physical_input')
    assert len(owned())==1
    ok('hot removal: old module released, surviving physical capture selected and filter rebound')
    client.command('disable');client.wait(lambda x:not x['enabled'])
    select();client.wait(lambda x:x['available'])
    # Exercise cancellation of native operations; never leave busy stuck.
    os.kill(server.pid,signal.SIGSTOP)
    try:
        client.command('enable');client.wait(lambda x:bool(x['error']) and not x['available'],limit=8)
    finally:os.kill(server.pid,signal.SIGCONT)
    client.command('refresh');client.wait(lambda x:x['enabled'])
    client.command('disable');client.wait(lambda x:not x['enabled']);assert not owned()
    ok('unresponsive server: bounded timeout, callback cancellation, recovery, no stuck busy state')
    client.stop()
    ui_smoke()

BUS_PID=None
try:
    run()
finally:
    for p in reversed(PROCESSES):
        if p.poll() is None:
            p.send_signal(signal.SIGCONT);p.terminate()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait()
    if BUS_PID:os.kill(BUS_PID,signal.SIGTERM)
    for f in LOGS:f.close()
    dest=ROOT/'validation'/('logs-'+RUN_NAME);dest.mkdir(exist_ok=True)
    for f in TEMP.glob('*.log'):dest.joinpath(f.name).write_bytes(f.read_bytes())
    FIXTURE.joinpath(RUN_NAME+'-results.json').write_text(json.dumps({'server':KIND,'passes':RESULTS,'runtime':str(TEMP)},indent=2)+'\n')
    print('Isolated runtime (no host audio):',TEMP,flush=True)
