"""Opt-in Clash-only local controller. Foreground and image gates precede input."""
import argparse,json,subprocess,time,uuid,os
from pathlib import Path
import cv2,numpy as np
from studio.recognize import Cards,Units,Tracker,clock_candidate
from .policy import Policy,PressureLearner
from .games import Games

class Bridge:
    def __init__(self,path):self.proc=subprocess.Popen([str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    def request(self,**request):
        self.proc.stdin.write(json.dumps(request)+'\n');self.proc.stdin.flush()
        line=self.proc.stdout.readline()
        if not line:raise RuntimeError('Native mirror bridge stopped')
        result=json.loads(line)
        if result.get('error'):raise RuntimeError(result['error'])
        return result
    def close(self):
        self.proc.terminate()
        try:self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:self.proc.kill()

def calibrate(image,cards):
    h,w=image.shape[:2];choices=[]
    # Search bounded portrait crops; scoring is purely current deck icon evidence.
    for margin in [0,8,16,24]:
        cw=w-2*margin;ch=round(cw*2.174)
        if ch>h:continue
        for top in range(0,h-ch+1,max(1,(h-ch)//8)):
            crop=image[top:top+ch,margin:margin+cw];hand=cards.hand(cv2.resize(crop,(442,960)))
            score=sum(s.get('geometric_inliers',0) for s in hand if s['name'])
            if sum(bool(s['name']) for s in hand)>=3:choices.append((score,[margin,top,cw,ch]))
    return max(choices,key=lambda v:v[0])[1] if choices else None

def visible_elixir(text,image=None):
    import re
    values=[int(t['text']) for t in text if re.fullmatch(r'(?:10|[0-9])',t['text']) and t.get('confidence',0)>=.9 and .24<t['box'][0]<.34 and .935<t['box'][1]<.97]
    value=values[0] if len(values)==1 else None
    if image is None:return value
    h,w=image.shape[:2];hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV);estimates=[]
    for yy in [.950,.954,.958]:
        row=hsv[round(yy*h),int(.29*w):int(.955*w)]
        mask=(row[:,0]>135)&(row[:,0]<175)&(row[:,1]>130)&(row[:,2]>100)
        indices=np.where(mask)[0]
        estimates.append(float((indices[-1]+1)/len(row)*10) if len(indices) else 0.0)
    if max(estimates)-min(estimates)>.3:return None
    bar=float(np.median(estimates))
    # Independent gauge pixels catch 6/9 OCR confusion. If text is unreadable,
    # use a conservative lower bound, never an invented exact resource count.
    if value is not None:return value if abs(value-bar)<=.6 else None
    return max(0,min(10,int(np.floor(bar-.3))))

def sides(image,objects):
    # Tentative red/blue badge segmentation; unknown stays unknown.
    h,w=image.shape[:2]
    for o in objects:
        a,b,c,d=o['box'];patch=image[max(0,int((b-.02)*h)):max(0,int((b+(d-b)*.28)*h)),max(0,int(a*w)):min(w,int(c*w))]
        o['side']='unknown'
        if patch.size==0:continue
        hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
        red=((hsv[:,:,0]<10)|(hsv[:,:,0]>170))&(hsv[:,:,1]>170)&(hsv[:,:,2]>100)
        blue=(hsv[:,:,0]>95)&(hsv[:,:,0]<125)&(hsv[:,:,1]>170)&(hsv[:,:,2]>100)
        r,bl=float(red.mean()),float(blue.mean())
        if r>.10 and bl<.02:o['side']='enemy'
        elif bl>.10 and r<.02:o['side']='own'
        o['side_basis']='experimental badge-color heuristic'
    return objects

def result_outcome(text,player,opponent):
    import re
    norm=lambda x:re.sub('[^a-z0-9]','',x.lower())
    winners=[t for t in text if norm(t['text']) in ['winner','victory','defeat'] and t.get('confidence',0)>=.9]
    if len(winners)!=1:return 'unknown'
    winner=winners[0];word=norm(winner['text'])
    if word in ['victory','defeat']:return 'win' if word=='victory' else 'loss'
    near=[norm(t['text']) for t in text if abs(t['box'][1]-winner['box'][1])<.12 and t.get('confidence',0)>=.9]
    if norm(player) in near and (not opponent or norm(opponent) not in near):return 'win'
    if opponent and norm(opponent) in near and norm(player) not in near:return 'loss'
    return 'unknown'

def main():
    p=argparse.ArgumentParser();p.add_argument('--bridge',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--control',action='store_true');p.add_argument('--player-name',default='Sample');p.add_argument('--max-seconds',type=int,default=360);p.add_argument('--heartbeat',type=Path)
    a=p.parse_args();a.data.mkdir(parents=True,exist_ok=True);bridge=Bridge(a.bridge)
    cards=Cards(a.models/'cards');units=Units(a.models/'units_M_480x352.onnx');tracker=Tracker();policy=Policy();learner=PressureLearner(a.data/'pressure-learning.json');threshold=learner.choose()
    journal=Games(a.data/'games.sqlite3');game=journal.start('baseline-v1-pressure-'+str(threshold),'live')
    parent_pid=os.getppid();crop=None;pending=None;focused=False;opponent=None;previous_elixir=None;previous_time=0;index=0;started=time.monotonic();outcome='unknown'
    try:
        status=bridge.request(command='status');print(json.dumps(status),flush=True)
        if status.get('front_app')=='com.apple.loginwindow':raise RuntimeError('Mac is locked; no capture or input performed')
        if not status['screen_permission'] or (a.control and not status['input_permission']):raise RuntimeError('Existing macOS screen/input permissions are required; none were requested automatically')
        while time.monotonic()-started<a.max_seconds:
            if (a.data/'STOP').exists():break
            if os.getppid()!=parent_pid:raise RuntimeError('Parent controller disappeared; input stopped')
            if a.heartbeat and (not a.heartbeat.exists() or time.time()-a.heartbeat.stat().st_mtime>6):raise RuntimeError('Dashboard heartbeat expired; input stopped')
            captured=time.monotonic_ns();path=a.data/'latest-window.png';cap=bridge.request(command='capture',path=str(path))
            image=cv2.imread(str(path))
            if crop is None:crop=calibrate(image,cards)
            if crop is None:raise RuntimeError('No calibrated Clash Royale hand found. Mirror must show Clash Royale; no input performed')
            x,y,w,h=crop;frame=cv2.resize(image[y:y+h,x:x+w],(442,960));framepath=a.data/'latest-clash.png';cv2.imwrite(str(framepath),frame)
            text=bridge.request(command='analyze',path=str(framepath),fast=True)['text'];clock=clock_candidate({'text':text});hand=cards.hand(frame)
            if not clock:
                text=bridge.request(command='analyze',path=str(framepath))['text']
                outcome=result_outcome(text,a.player_name,opponent)
                if outcome in ['win','loss']:
                    journal.record(game,'outcome',{'result':outcome,'evidence':text});break
                raise RuntimeError('Clash battle signature lost; stopped before input')
            if sum(bool(s['name']) for s in hand)<2:raise RuntimeError('Clash hand signature lost; stopped before input')
            if a.control and not focused:
                bridge.request(command='focus');focused=True;continue
            if opponent is None:
                text_for_name=bridge.request(command='analyze',path=str(framepath))['text']
                opponent=next((t['text'] for t in text_for_name if .055<t['box'][1]<.095 and t['box'][0]<.3 and len(t['text'])>=3),None)
            elixir=visible_elixir(text,frame);now=time.monotonic();age=(time.monotonic_ns()-captured)/1e6
            state={'battle':True,'hand':hand,'objects':sides(frame,tracker.update(units.detect(frame),index)),
                'elixir':elixir,'elixir_basis':'OCR checked against gauge pixels, or conservative gauge lower bound','elixir_verified':elixir is not None and elixir==previous_elixir and now-previous_time<1,
                'age_ms':(time.monotonic_ns()-captured)/1e6,'clock':clock,'crop':crop,'sequence':cap['sequence']}
            previous_elixir,previous_time=elixir,now;index+=1
            journal.record(game,'observation',state)
            if pending:
                next_card=next((s['name'] for s in hand if s['slot']==pending['action']['slot']),None)
                spent=elixir is not None and elixir<=pending['before']-pending['action']['cost']+1
                if next_card and next_card!=pending['action']['card'] and spent:
                    journal.record(game,'input',{'status':'deployment_inferred','action':pending['action'],'basis':'hand identity changed and visible elixir decreased; exact placement remains unverified'})
                    pending=None
                elif now-pending['time']>2:
                    raise RuntimeError('Deployment was not confirmed by hand/resource changes; further input stopped')
                else:
                    continue
            action=policy.choose(state,now,threshold);journal.record(game,'decision',{'action':action,'mode':'control' if a.control else 'shadow'})
            if action and a.control:
                # Capture freshness is enforced again by the native bridge. Never tap a menu.
                result=bridge.request(command='play',sequence=cap['sequence'],crop=crop,slot=action['slot'],point=action['point'])
                journal.record(game,'input',dict(action,result=result));policy.committed(action,now)
                pending={'action':action,'before':elixir,'time':now}
            print(json.dumps({'sequence':index,'elapsed_ms':round((time.monotonic_ns()-captured)/1e6),'elixir':elixir,'action':action,'mode':'control' if a.control else 'shadow'}),flush=True)
    except Exception as exc:
        outcome='disconnected';journal.record(game,'outcome',{'error':str(exc)});print(json.dumps({'blocked':str(exc),'phone_input_stopped':True}),flush=True)
    finally:
        journal.finish(game,outcome);bridge.close()
        # Unknown/disconnected games never change the learner.
        learner.finish(threshold,outcome)
        print(json.dumps({'game':game,'outcome':outcome,'learning_updated':outcome in ['win','loss']}),flush=True)
if __name__=='__main__':main()
