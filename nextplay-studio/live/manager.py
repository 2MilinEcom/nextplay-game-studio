"""Local dashboard lifecycle for the opt-in player prototype."""
import json,subprocess,threading,os,signal
from pathlib import Path
class Manager:
    def __init__(self,app,data):
        self.app=Path(app);self.data=Path(data)/'player';self.data.mkdir(parents=True,exist_ok=True)
        self.bridge=self.app/'NextPlay Player.app/Contents/MacOS/NextPlayPlayer';self.proc=None;self.last={};self.lock=threading.Lock()
    def permissions(self):
        if not self.bridge.exists():return {'error':'Native player helper not installed'}
        try:
            p=subprocess.run([str(self.bridge)],input='{"command":"status"}\n',text=True,capture_output=True,timeout=5)
            return json.loads(p.stdout.splitlines()[-1])
        except Exception:return {'error':'Player helper unavailable'}
    def status(self):
        (self.data/'heartbeat').touch()
        with self.lock:return {'running':self.proc is not None and self.proc.poll() is None,'last':dict(self.last),'permissions':self.permissions(),'prototype':True}
    def start(self,control=False):
        with self.lock:
            if self.proc and self.proc.poll() is None:raise ValueError('Player already running')
            permissions=self.permissions()
            if not permissions.get('screen_permission'):raise ValueError('macOS Screen Recording access is missing')
            if control and not permissions.get('input_permission'):raise ValueError('macOS Accessibility access for the player helper is missing. No phone input was performed.')
            (self.data/'STOP').unlink(missing_ok=True)
            (self.data/'heartbeat').touch()
            cmd=[str(self.app/'.vision-venv/bin/python'),'-m','live.controller','--bridge',str(self.bridge),'--models',str(self.app/'models'),'--data',str(self.data),'--heartbeat',str(self.data/'heartbeat')]
            if control:cmd.append('--control')
            self.last={'state':'starting','mode':'control' if control else 'shadow'}
            self.proc=subprocess.Popen(cmd,cwd=self.app,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            proc=self.proc
            threading.Thread(target=self.consume,args=(proc,),daemon=True).start()
            return dict(self.last)
    def consume(self,proc):
        with (self.data/'session-output.ndjson').open('a') as log:
            for line in proc.stdout:
                try:row=json.loads(line)
                except Exception:continue
                log.write(line);log.flush()
                with self.lock:self.last=row
        errors=proc.stderr.read();proc.wait()
        if errors:(self.data/'diagnostics.log').write_text(errors[-16000:])
        with self.lock:
            if proc.returncode:self.last={'state':'failed','error':'Player process stopped. Check local diagnostics.'}
    def stop(self):
        (self.data/'STOP').write_text('stop')
        with self.lock:
            if self.proc and self.proc.poll() is None:os.killpg(self.proc.pid,signal.SIGTERM)
            self.last={'state':'stopped','phone_input_stopped':True}
        return dict(self.last)
