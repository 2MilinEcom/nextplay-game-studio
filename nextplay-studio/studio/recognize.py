"""Offline perception only: card features, local ONNX units, conservative tracks.

No network clients, game input, hidden-state reconstruction or paid providers.
"""
import argparse
import ast
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import onnxruntime as ort

ort.disable_telemetry_events()
cv2.setNumThreads(2)
SLOTS = [(.225 + .190*i, .837, .178, .106) for i in range(4)]
# Portrait capture profile. Stationary tower graphics produced false positives
# in evaluation; exclude their centers, accepting reduced recall near towers.
TOWERS = [(.10,.20,.30,.31),(.70,.20,.91,.31),(.38,.10,.63,.25),
          (.08,.58,.31,.70),(.69,.58,.93,.70),(.36,.65,.64,.79)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def layout_supported(image):
    h,w=image.shape[:2]
    return 2.12 <= h/w <= 2.25


def clock_candidate(row):
    import re
    return next((t['text'] for t in row.get('text',[]) if
                 re.fullmatch(r'[0-3]:[0-5][0-9]',t['text']) and
                 t['box'][0]>.80 and .045<t['box'][1]<.15),None)


def label_cues(row,names):
    import re
    result=[]
    for item in row.get('text',[]):
        if not .25 < item['box'][1] < .80:continue
        value=re.sub('[^a-z]','',item['text'].lower())
        for name in names:
            normalized=re.sub('[^a-z]','',name.lower())
            if len(normalized)>=5 and normalized in value:
                result.append({'name':name,'text':item['text'],'box':item['box'],
                               'meaning':'Visible card-name text cue, not proof of deployment or unit identity.'})
    return result


def overlap(a,b):
    left,top=max(a[0],b[0]),max(a[1],b[1]);right,bottom=min(a[2],b[2]),min(a[3],b[3])
    area=max(0,right-left)*max(0,bottom-top)
    return area/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


class Cards:
    def __init__(self, directory):
        self.sift=cv2.SIFT_create(nfeatures=150,contrastThreshold=.012)
        self.matcher=cv2.BFMatcher();self.templates=[]
        self.names=set()
        for item in json.loads((directory/'manifest.json').read_text()):
            path=directory/item['file']
            if path.parent != directory or digest(path)!=item['sha256']:
                raise ValueError('Card template checksum mismatch')
            im=cv2.imread(str(path));h,w=im.shape[:2]
            gray=cv2.cvtColor(im[int(.2*h):int(.9*h),int(.08*w):int(.92*w)],cv2.COLOR_BGR2GRAY)
            kp,desc=self.sift.detectAndCompute(gray,None)
            if desc is not None:
                self.templates.append((item['name'],kp,desc));self.names.add(item['name'])

    def match(self,crop):
        gray=cv2.cvtColor(cv2.resize(crop,None,fx=2,fy=2),cv2.COLOR_BGR2GRAY)
        kp,desc=self.sift.detectAndCompute(gray,None)
        best={}
        if desc is not None and len(desc)>=6:
            for name,tkp,td in self.templates:
                pairs=self.matcher.knnMatch(desc,td,k=2)
                good=[p[0] for p in pairs if len(p)==2 and p[0].distance < .72*p[1].distance and p[0].distance<300]
                # Avoid inflated evidence from repeated template keypoints.
                unique={}
                for m in sorted(good,key=lambda m:m.distance):
                    unique.setdefault(m.trainIdx,m)
                good=list(unique.values())
                inliers=0
                if len(good)>=6:
                    source=np.float32([tkp[m.trainIdx].pt for m in good])
                    target=np.float32([kp[m.queryIdx].pt for m in good])
                    matrix,mask=cv2.findHomography(source,target,cv2.RANSAC,4)
                    if matrix is not None and mask is not None and np.isfinite(matrix).all():
                        inliers=int(mask.sum())
                score={'name':name,'matches':len(good),'inliers':inliers}
                if inliers>best.get(name,{}).get('inliers',-1):best[name]=score
        ranked=sorted(best.values(),key=lambda x:(x['inliers'],x['matches']),reverse=True)
        first=ranked[0] if ranked else {'name':None,'matches':0,'inliers':0}
        margin=first['inliers']-(ranked[1]['inliers'] if len(ranked)>1 else 0)
        accepted=first['inliers']>=8 and first['matches']>=10 and margin>=4
        return {'name':first['name'] if accepted else None,'feature_matches':first['matches'],
                'geometric_inliers':first['inliers'],'runner_up_margin':margin,
                'status':'matched' if accepted else 'unknown','confidence':'UNVERIFIED',
                'reason':None if accepted else 'Not enough distinct, geometrically consistent features'}

    def hand(self,image):
        h,w=image.shape[:2];result=[]
        for i,(x,y,bw,bh) in enumerate(SLOTS):
            crop=image[int(y*h):int((y+bh)*h),int(x*w):int((x+bw)*w)]
            result.append(dict(self.match(crop),slot=i+1,box=[x,y,bw,bh]))
        # A normal four-card hand cannot contain duplicate cards; reject ambiguity.
        counts=Counter(s['name'] for s in result if s['name'])
        for slot in result:
            if slot['name'] and counts[slot['name']]>1:
                slot.update(name=None,status='unknown',reason='Duplicate slot identity is ambiguous')
        return result


class Units:
    def __init__(self,path):
        manifest=json.loads(path.with_name('units-manifest.json').read_text())
        if digest(path)!=manifest['sha256']:raise ValueError('Unit model checksum mismatch')
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.input=self.session.get_inputs()[0]
        if self.input.shape != [1,3,480,352] or self.input.type!='tensor(float16)':
            raise ValueError('Unexpected detector input contract')
        raw=self.session.get_modelmeta().custom_metadata_map['names']
        if len(raw)>20000:raise ValueError('Invalid class map')
        self.names=ast.literal_eval(raw)
        self.manifest=manifest

    def detect(self,image):
        rgb=Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB));w,h=rgb.size
        y0,y1=round(.05*h),round(.80*h);crop=rgb.crop((0,y0,w,y1));cw,ch=crop.size
        ratio=min(352/cw,480/ch);nw,nh=int(cw*ratio),int(ch*ratio)
        dx,dy=352-nw,480-nh;left,top=dx-dx//2,dy-dy//2
        array=np.array(crop.resize((nw,nh)),dtype=np.float16)
        blob=np.pad(array,((top,dy//2),(left,dx//2),(0,0)),constant_values=114).transpose(2,0,1)[None]/255
        output=self.session.run(None,{self.input.name:blob})[0]
        if output.shape!=(1,300,6):raise ValueError('Unexpected detector output contract')
        result=[]
        for row in output[0]:
            if not np.isfinite(row).all() or row[4]<.90:continue
            class_id=int(row[5])
            if class_id not in self.names:continue
            x1,x2=(float(row[0])-left)*cw/nw,(float(row[2])-left)*cw/nw
            yy1,yy2=(float(row[1])-top)*ch/nh+y0,(float(row[3])-top)*ch/nh+y0
            box=[max(0,min(1,x1/w)),max(0,min(1,yy1/h)),max(0,min(1,x2/w)),max(0,min(1,yy2/h))]
            if box[2]<=box[0] or box[3]<=box[1]:continue
            cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
            if not .13<cy<.76 or any(a<=cx<=c and b<=cy<=d for a,b,c,d in TOWERS):continue
            result.append({'label':self.names[class_id],'score':round(float(row[4]),4),'box':box,
                           'side':'unknown','status':'candidate','confidence':'UNVERIFIED'})
        return result


class Tracker:
    def __init__(self):self.tracks={};self.next_id=1
    def update(self,objects,index):
        self.tracks={k:v for k,v in self.tracks.items() if index-v['last']<=2}
        used=set()
        for obj in sorted(objects,key=lambda d:-d['score']):
            cx,cy=(obj['box'][0]+obj['box'][2])/2,(obj['box'][1]+obj['box'][3])/2
            candidates=[]
            for key,track in self.tracks.items():
                if key in used or track['label']!=obj['label']:continue
                box=track['box'];tx,ty=(box[0]+box[2])/2,(box[1]+box[3])/2
                distance=math.hypot(cx-tx,cy-ty)
                if distance<.10 and (overlap(box,obj['box'])>.05 or distance<.04):candidates.append((distance,key))
            key=min(candidates)[1] if candidates else self.next_id
            if not candidates:self.next_id+=1
            previous=self.tracks.get(key);hits=previous['hits']+1 if previous else 1
            self.tracks[key]={'label':obj['label'],'box':obj['box'],'last':index,'hits':hits}
            used.add(key);obj.update(track_id=key,track_hits=hits,status='repeated_candidate' if hits>=3 else 'candidate')
        return objects


def annotate(image,row,target):
    h,w=image.shape[:2]
    for slot in row['hand']:
        x,y,bw,bh=slot['box'];left,top=int(x*w),int(y*h)
        cv2.rectangle(image,(left,top),(int((x+bw)*w),int((y+bh)*h)),(255,180,0),2)
        cv2.putText(image,slot['name'] or 'unknown',(left,max(12,top-4)),cv2.FONT_HERSHEY_SIMPLEX,.32,(255,255,255),1,cv2.LINE_AA)
    for obj in row['objects']:
        a,b,c,d=obj['box'];left,top=int(a*w),int(b*h)
        cv2.rectangle(image,(left,top),(int(c*w),int(d*h)),(0,220,100),2)
        cv2.putText(image,f"{obj['label']} {obj['score']:.2f}",(left,max(12,top-4)),cv2.FONT_HERSHEY_SIMPLEX,.35,(255,255,255),1,cv2.LINE_AA)
    cv2.putText(image,'LOCAL PREDICTIONS - VERIFY',(8,22),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,255),1,cv2.LINE_AA)
    cv2.imwrite(str(target),image,[cv2.IMWRITE_JPEG_QUALITY,85])


def run(directory,models):
    timeline=[json.loads(l) for l in (directory/'local-timeline.ndjson').read_text().splitlines()]
    paths=(directory/'local-input.txt').read_text().splitlines()
    cards=Cards(models/'cards');units=Units(models/'units_M_480x352.onnx');tracker=Tracker()
    start=time.monotonic();rows=[];last_clock=-99
    for old in directory.glob('f[0-9][0-9][0-9][0-9]-overlay.jpg'):
        old.unlink()
    for row,path in zip(timeline,paths,strict=True):
        image=cv2.imread(path)
        if image is None:raise ValueError('Unreadable local frame')
        index=row['index'];supported=layout_supported(image)
        clock=clock_candidate(row)
        if clock:last_clock=index
        # Require local game-clock evidence, rather than looking through other app screens.
        active=supported and index-last_clock<=3
        hand=cards.hand(image) if active else []
        objects=tracker.update(units.detect(image),index) if active else []
        result={'index':index,'frame_id':Path(path).stem,'time_seconds':round((index+.5)/2,3),
                'layout_supported':supported,'gameplay_candidate':active,'clock_candidate':clock,'card_label_cues':label_cues(row,cards.names),
                'hand':hand,'objects':objects,'verification':'local_predictions_not_ground_truth'}
        if active and (index%20==0 or any(o['status']=='repeated_candidate' for o in objects)):
            annotate(image,result,directory/(Path(path).stem+'-overlay.jpg'));result['overlay']=True
        rows.append(result)
    hand_slots=sum(len(r['hand']) for r in rows);matched=sum(bool(s['name']) for r in rows for s in r['hand'])
    summary={'version':1,'processing':'local','api_cost_usd':0,'elapsed_seconds':round(time.monotonic()-start,2),
        'frames_analyzed':len(rows),'gameplay_candidate_frames':sum(r['gameplay_candidate'] for r in rows),
        'matched_hand_slots':matched,'total_hand_slots':hand_slots,'hand_coverage':round(matched/hand_slots,4) if hand_slots else 0,
        'card_names':sorted(set(s['name'] for r in rows for s in r['hand'] if s['name'])),
        'object_labels':sorted(set(o['label'] for r in rows for o in r['objects'] if o['status']=='repeated_candidate')),
        'model':units.manifest,'supported_object_classes':len(units.names),'known_missing_classes':['berserker','spirit_empress','newer evolutions'],
        'limits':['Hand matches are not proof a card was playable or deployed.', 'Model scores are not measured accuracy. Arena labels remain unverified.', 'Stationary tower regions are excluded; troops near towers may be missed.', 'Object tracks do not establish ownership, deployments, kills or exact placement.', 'Only portrait captures with aspect ratio 2.12–2.25 are supported. Other layouts fail closed.'],
        'timeline':rows}
    (directory/'local-recognition.json').write_text(json.dumps(summary,separators=(',',':')))
    print(json.dumps({k:v for k,v in summary.items() if k!='timeline'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--models',type=Path,required=True)
    args=parser.parse_args();run(args.directory,args.models)
