"""Small deck-specific baseline. Heuristics are not trained tactical expertise."""
import json,math
from pathlib import Path
COST={'Tesla':4,'Wall Breakers':2,'Miner':3,'Royal Delivery':3,'Poison':4,'Skeletons':1,'Berserker':2,'The Log':2}

class Policy:
    def __init__(self):self.last_action=-99;self.last_miner=-99;self.lane='left'
    def choose(self,state,now,pressure=9):
        if not state.get('battle') or not state.get('elixir_verified') or state.get('age_ms',999)>500:return None
        if now-self.last_action<1.0:return None
        hand={s['name']:s['slot'] for s in state.get('hand',[]) if s.get('name')}
        elixir=state['elixir'];threats=[o for o in state.get('objects',[]) if o.get('side')=='enemy' and o.get('track_hits',0)>=3]
        threats.sort(key=lambda o:-(o['box'][1]+o['box'][3])/2)
        def action(card,x,y,reason):
            if card not in hand or elixir<COST[card]:return None
            return {'card':card,'slot':hand[card],'point':[x,y],'reason':reason,'cost':COST[card]}
        for o in threats:
            a,b,c,d=o['box'];x,y=(a+c)/2,(b+d)/2
            if y<.42:continue
            lane='left' if x<.5 else 'right';self.lane=lane
            if o['label'] in ['prince','dark_prince','giant','golem','hog_rider','balloon','royal_ghost']:
                proposed=action('Tesla',.43 if lane=='left' else .57,.54,'central defense against repeated enemy candidate')
                if proposed:return proposed
            nearby=[t for t in threats if abs((t['box'][0]+t['box'][2])/2-x)<.18 and abs((t['box'][1]+t['box'][3])/2-y)<.12]
            if len(nearby)>=2:
                proposed=action('Poison',max(.12,min(.88,x)),max(.46,min(.68,y)),'multiple repeated enemy candidates in a defensive area')
                if proposed:return proposed
            if o['label'] in ['skeleton','skeletons','goblin','goblins','guards','spear_goblin','spear_goblins']:
                proposed=action('The Log',max(.12,min(.88,x)),.71,'ground swarm candidate in the same lane')
                if proposed:return proposed
            if y>.47:
                for card in ['Royal Delivery','Berserker','Skeletons']:
                    proposed=action(card,max(.12,min(.88,x)),max(.52,min(.69,y+.05)),'close defense against repeated enemy candidate')
                    if proposed:return proposed
        # Bounded baseline pressure, never infer opponent resources or card order.
        x=.21 if self.lane=='left' else .79
        if now-self.last_miner<5:
            return action('Wall Breakers',x,.46,'support a recent confirmed Miner input')
        if elixir>=pressure:
            for card,px,py in [('Miner',x,.24),('Wall Breakers',x,.46),('Berserker',x,.67),('Skeletons',.5,.72)]:
                proposed=action(card,px,py,'high visible elixir baseline pressure')
                if proposed:return proposed
        return None
    def committed(self,action,now):
        self.last_action=now
        if action['card']=='Miner':self.last_miner=now

class PressureLearner:
    """Per-game bandit between conservative pressure thresholds; no win guarantee."""
    def __init__(self,path):
        self.path=Path(path)
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'8':{'wins':0,'games':0},'9':{'wins':0,'games':0}}
    def choose(self):
        # Alternate unexplored arms, then use a bounded optimistic estimate.
        total=sum(v['games'] for v in self.data.values())
        return int(max(self.data,key=lambda k: (self.data[k]['wins']+1)/(self.data[k]['games']+2)+math.sqrt(math.log(total+2)/(self.data[k]['games']+1))))
    def finish(self,threshold,outcome):
        if outcome not in ['win','loss']:return
        arm=self.data[str(threshold)];arm['games']+=1;arm['wins']+=int(outcome=='win')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.partial');temp.write_text(json.dumps(self.data));temp.replace(self.path)
