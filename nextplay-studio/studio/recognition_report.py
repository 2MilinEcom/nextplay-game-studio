"""Describe local predictions without converting them to tactical facts."""

def card_changes(rows):
    events=[]
    last={}
    for row in rows:
        index=row['index']
        for slot in row['hand']:
            key=slot['slot'];name=slot['name'];previous=last.get(key)
            if not name:
                last.pop(key,None)
                continue
            if previous and previous['name']!=name and index-previous['index']==1:
                events.append({'slot':key,'from':previous['name'],'to':name,
                    'start_seconds':previous['time_seconds'],'end_seconds':row['time_seconds'],
                    'frame_ids':[previous['frame_id'],row['frame_id']],
                    'meaning':'Visible slot identity changed; deployment and placement are not established.'})
            last[key]={'name':name,'index':index,'time_seconds':row['time_seconds'],'frame_id':row['frame_id']}
    return events


def enrich(report,recognition):
    report['observations']=[o for o in report['observations'] if not o['id'].startswith('recognition-')]
    rows=recognition['timeline'];by_id={r['frame_id']:r for r in rows}
    changes=card_changes(rows)
    report['recognition']=dict(recognition,card_slot_changes=changes)
    for frame in report['frames']:
        frame['overlay']=by_id.get(frame['id'],{}).get('overlay',False)
    for observation in report['observations']:
        row=by_id.get(observation['frame_ids'][0])
        if not row or not row['gameplay_candidate']:continue
        hand=', '.join(f"{s['slot']}: {s['name'] or 'unknown'}" for s in row['hand'])
        units=', '.join(sorted(set(o['label'] for o in row['objects'] if o['status']=='repeated_candidate')))
        observation.update(kind='local_recognition',statement='Card matches and arena predictions to verify.',
            visible_evidence=f"Visible hand matching: {hand}. Repeated arena label candidates: {units or 'none accepted'}. These are local predictions, not verified game state.",
            recognition_frame=row['frame_id'])
    # Add a small selection of troop evidence that ordinary scene bookmarks miss.
    candidates=[r for r in rows if any(o['status']=='repeated_candidate' for o in r['objects'])]
    chosen=[]
    for row in candidates:
        if chosen and row['time_seconds']-chosen[-1]['time_seconds']<8:continue
        chosen.append(row)
        if len(chosen)==20:break
    existing={o['frame_ids'][0] for o in report['observations']}
    for row in chosen:
        if row['frame_id'] in existing:continue
        names=sorted(set(o['label'] for o in row['objects'] if o['status']=='repeated_candidate'))
        report['observations'].append({'id':f"recognition-{row['frame_id']}",'kind':'local_unit_prediction','confidence':'LOW',
            'sample_start_seconds':row['time_seconds'],'frame_ids':[row['frame_id']],
            'statement':'Repeated local unit predictions: '+', '.join(names)+'.',
            'visible_evidence':'A local detector proposed these labels in multiple samples. Verify the green boxes; track continuity is not independent confirmation.'})
    report['observations'].sort(key=lambda o:o['sample_start_seconds'])
    summary=(f"Local recognition complete: {recognition['frames_analyzed']} frames; "
             f"{recognition['matched_hand_slots']} of {recognition['total_hand_slots']} card slots matched "
             f"({recognition['hand_coverage']:.0%} coverage, not accuracy). "
             f"Recognized card names: {', '.join(recognition['card_names']) or 'none'}. "
             f"Repeated arena label candidates: {', '.join(recognition['object_labels']) or 'none'}. "
             'No paid API calls. Unknown cards and uncertain objects remain unresolved.')
    evidence=[o['id'] for o in report['observations'] if o['kind']=='local_recognition']
    priorities=[]
    if evidence:
        priorities.append({'title':'Verify your visible card rotation','goal':'Review five card-slot transitions at normal playback speed.',
            'measurement':'Five transitions checked against the screenshots and recording.',
            'review_question':'Which card changes in the visible hand? Confirm the actual play in the replay; slot changes alone do not establish deployments or placements.',
            'evidence_ids':evidence[:5]})
    unit_evidence=[o['id'] for o in report['observations'] if o['kind']=='local_unit_prediction']
    if unit_evidence:
        priorities.append({'title':'Check the detected arena units','goal':'Verify three highlighted unit sequences before drawing tactical conclusions.',
            'measurement':'Three sequences labeled correct, incorrect, or uncertain in your review notes.',
            'review_question':'Do the visible sprites agree with the predicted labels? New cards and evolutions may be missing from this model.',
            'evidence_ids':unit_evidence[:3]})
    report['coaching']={'summary':summary,'confidence':'LOW','priorities':priorities}
    report['unknowns']=[x for x in report['unknowns'] if not x.startswith('Troop identity,')]
    report['unknowns']+=recognition['limits']+['Exact elixir, enemy hand, deployment coordinates, and causal tactical mistakes remain unknown.',
        'Newer arena units including Berserker and Spirit Empress are outside the model’s class list.']
    report['data_limits']=[x for x in report['data_limits'] if not x.startswith('Local OCR and visual changes')]
    report['data_limits']+=['Local card feature matches and trained unit detections are predictions; repeated tracks are not independent verification.']
    report['provenance'].update(recognition_model=recognition['model'],observation_basis='Local Apple OCR, card feature matching, ONNX unit predictions and conservative tracks')
    return report
