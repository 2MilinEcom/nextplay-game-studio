"""Replay speed measurement: explicitly does not measure playing strength."""
import argparse,json,statistics,time
from pathlib import Path
from .perception import Perception
p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True);p.add_argument('--frames',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();rows=[json.loads(l) for l in (a.frames/'local-timeline.ndjson').read_text().splitlines()]
engine=Perception(a.models);results=[]
for r in rows:
    if r['index']%20:continue
    path=a.frames/f"f{r['index']:04d}.jpg"
    result=engine.frame(path,r.get('text',[]),replay=True)
    if result['active_candidate']:results.append(result)
latencies=sorted(r['inference_ms'] for r in results)
report={'mode':'offline_replay_benchmark','frames':len(results),'model_kept_loaded':True,
    'median_inference_ms':statistics.median(latencies) if latencies else None,
    'p95_inference_ms':latencies[min(len(latencies)-1,int(len(latencies)*.95))] if latencies else None,
    'phone_control_tested':False,'capture_and_ocr_latency_included':False,'playing_strength_tested':False,
    'api_calls':0,'timeline':results}
a.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='timeline'}))
