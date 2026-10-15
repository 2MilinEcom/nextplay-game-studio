"""Offline outcome rules. No causal blame, hidden state, or network calls."""
from collections import Counter
import re


def evaluate(report):
    active={r['index'] for r in report.get('recognition',{}).get('timeline',[]) if r.get('gameplay_candidate')}
    readings=[]; events=[]; pending={}; confirmed={}
    # Repeated OCR agrees across two consecutive one-second samples. Missing
    # counters break continuity; increases are never treated as healing or damage.
    for row in report.get('local_timeline',[]):
        i=row['index']; t=row.get('time_seconds',(i+.5)/2)
        if i%2: continue
        if i not in active:
            pending.clear(); confirmed.clear(); continue
        counters=row.get('counters',{})
        for name in list(pending):
            if name not in counters: pending.pop(name,None)
        for name,item in counters.items():
            value=item['value']; previous=pending.get(name)
            box=item.get('box')
            if box and any(re.search('[A-Za-z]',text['text']) and
                box[1]-.04 <= text['box'][1] <= box[1]-.008 and
                text['box'][0] < box[0]+box[2] and text['box'][0]+text['box'][2]>box[0]
                for text in row.get('text',[])):
                pending.pop(name,None); continue
            baseline=confirmed.get(name)
            if baseline and value>baseline['value']:
                pending.pop(name,None); continue
            if previous and previous['value']==value and i-previous['index']==2:
                reading={'tower':name,'value':value,'time_seconds':t,'index':i,'frame_id':f'f{i:04d}',
                         'confirmation_frames':[f"f{previous['index']:04d}",f'f{i:04d}']}
                readings.append(reading)
                old=confirmed.get(name)
                if old and i-old['index']<=8 and 0<old['value']-value<=2500:
                    damage=old['value']-value
                    events.append({'id':f'outcome-{name}-{i}','kind':'tower_damage_outcome','confidence':'MEDIUM',
                        'grade':'favorable' if name.startswith('enemy') else 'unfavorable',
                        'sample_start_seconds':old['time_seconds'],'end_seconds':t,
                        'frame_ids':list(dict.fromkeys(old['confirmation_frames']+reading['confirmation_frames'])),
                        'tower':name,'damage':damage,'before':old['value'],'after':value,
                        'statement':f"{'Favorable' if name.startswith('enemy') else 'Unfavorable'} outcome: {name.replace('_',' ')} tower lost {damage} HP.",
                        'visible_evidence':f"Repeated local counter readings fell from {old['value']} to {value} between {old['time_seconds']:.1f}s and {t:.1f}s. This grades visible damage, not the decision or card responsible."})
                confirmed[name]=reading
            pending[name]={'value':value,'index':i}
    counts=Counter(e['grade'] for e in events)
    report['evaluation']={'version':1,'method':'Repeated cropped counter OCR and deterministic damage rules',
        'api_cost_usd':0,'readings':readings,'events':events,'counts':dict(counts),
        'limits':['Favorable/unfavorable labels describe tower damage outcomes, not good/bad decisions.',
        'No spell value, successful defense, elixir waste, optimal placement, or causal mistake is scored without verified evidence.',
        'Unreadable counters, destroyed towers, layout changes, and gaps produce no score. Damage below 100 remaining HP is not read.',
        'OCR agreement reduces errors but is not independent verification. Check linked screenshots.'],
        'unsupported_rules':['spell value','defense quality','elixir waste','complete tower trades']}
    report['observations']=[o for o in report['observations'] if not o['id'].startswith('outcome-')]+events
    report['observations'].sort(key=lambda o:o['sample_start_seconds'])
    base=report['coaching']['summary'].split(' Local outcome rules:')[0]
    report['coaching']['summary']=base+f" Local outcome rules: {counts['favorable']} favorable and {counts['unfavorable']} unfavorable tower-damage events; {len(readings)} repeated counter readings. Decisions with insufficient evidence stay ungraded."
    priorities=[]
    for grade,title in [('unfavorable','Review the largest damage conceded'),('favorable','Review your largest damage dealt')]:
        selected=sorted((e for e in events if e['grade']==grade),key=lambda e:e['damage'],reverse=True)[:3]
        if selected:
            priorities.append({'title':title,'goal':'Replay these damage intervals and compare the visible response.',
                'measurement':'; '.join(f"{e['sample_start_seconds']:.1f}–{e['end_seconds']:.1f}s: {e['damage']} HP" for e in selected),
                'review_question':'What visibly happened during this interval? The counter change alone cannot establish which play was right or wrong.',
                'evidence_ids':[e['id'] for e in selected]})
    report['coaching']['priorities']=priorities
    return report
