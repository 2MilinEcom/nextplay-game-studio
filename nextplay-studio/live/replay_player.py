"""Run the complete OCR/perception/policy path on a Clash replay; never click."""
import argparse,json,time,statistics
from pathlib import Path
import cv2
from studio.recognize import Cards,Units,Tracker,clock_candidate
from .controller import Bridge,visible_elixir,sides
from .policy import Policy
p=argparse.ArgumentParser();p.add_argument('--bridge',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--frames',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();bridge=Bridge(a.bridge);cards=Cards(a.models/'cards');units=Units(a.models/'units_M_480x352.onnx');tracker=Tracker();policy=Policy();rows=[];previous=None
try:
 for index in range(20,548,2):
    path=a.frames/f'f{index:04d}.jpg'
    if not path.exists():continue
    started=time.monotonic_ns();image=cv2.imread(str(path));text=bridge.request(command='analyze',path=str(path),fast=True)['text'];clock=clock_candidate({'text':text})
    elixir=visible_elixir(text,image)
    hand=cards.hand(image) if clock else []
    objects=sides(image,tracker.update(units.detect(image),index//2)) if clock else []
    elapsed=(time.monotonic_ns()-started)/1e6
    state={'battle':bool(clock),'hand':hand,'objects':objects,'elixir':elixir,'elixir_verified':elixir is not None and previous==elixir,'age_ms':elapsed}
    action=policy.choose(state,index/2)
    if action:policy.committed(action,index/2)
    rows.append({'frame':path.name,'clock':clock,'elixir':elixir,'elixir_confirmed':state['elixir_verified'],'elapsed_ms':elapsed,'action':action,'objects':objects})
    previous=elixir
finally:bridge.close()
latencies=sorted(r['elapsed_ms'] for r in rows)
report={'mode':'offline_shadow_replay','frames':len(rows),'clock_frames':sum(bool(r['clock']) for r in rows),
 'elixir_read_frames':sum(r['elixir'] is not None for r in rows),'confirmed_elixir_frames':sum(r['elixir_confirmed'] for r in rows),
 'proposed_actions':sum(r['action'] is not None for r in rows),'median_ocr_perception_policy_ms':statistics.median(latencies),
 'p95_ocr_perception_policy_ms':latencies[min(len(latencies)-1,int(len(latencies)*.95))],
 'native_input_calls':0,'live_capture_latency_included':False,'playing_strength_verified':False,'timeline':rows}
a.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='timeline'}))
