"""Load local models once; JSON-line frames in, predictions out. No input APIs."""
import json,time,argparse,sys
from pathlib import Path
import cv2
from studio.recognize import Cards,Units,Tracker,clock_candidate,layout_supported

class Perception:
    def __init__(self,models):
        self.cards=Cards(models/'cards');self.units=Units(models/'units_M_480x352.onnx')
        self.tracker=Tracker();self.sequence=0
    def frame(self,path,ocr,captured_ns=None,replay=False):
        started=time.monotonic_ns()
        image=cv2.imread(str(path))
        if image is None:raise ValueError('Unreadable frame')
        supported=layout_supported(image);clock=clock_candidate({'text':ocr})
        active=supported and clock is not None
        objects=self.tracker.update(self.units.detect(image),self.sequence) if active else []
        result={'sequence':self.sequence,'frame':str(path),'active_candidate':active,
            'clock':clock,'hand':self.cards.hand(image) if active else [],'objects':objects,
            'inference_ms':(time.monotonic_ns()-started)/1e6,'replay':replay,
            'age_ms':(time.monotonic_ns()-captured_ns)/1e6 if captured_ns is not None else None,
            'action':None,'status':'observation_only',
            'unknown':['unit ownership','deployment events','validated elixir','tile calibration']}
        self.sequence+=1
        return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True);p.add_argument('--output',type=Path)
    args=p.parse_args();engine=Perception(args.models)
    out=args.output.open('a') if args.output else None
    try:
        for line in sys.stdin:
            try:
                req=json.loads(line)
                # The producer supplies a monotonic capture time; never substitute receipt time.
                result=engine.frame(req['path'],req.get('ocr',[]),req.get('captured_ns'),req.get('replay',False))
            except Exception as exc:result={'status':'error','action':None,'error':str(exc)}
            payload=json.dumps(result);print(payload,flush=True)
            if out:out.write(payload+'\n');out.flush()
    finally:
        if out:out.close()

if __name__=='__main__':main()
