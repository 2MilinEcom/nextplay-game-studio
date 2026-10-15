'use strict';
const $ = id => document.getElementById(id);
const state = { token: '', status: null, jobs: [], view: 'home', selected: null, detailUpdated: null, liveId: null, stream: null, timer: null, sending: false, stopping: false, uploadBusy: false };
const labels = {home:'Overview', library:'Recordings', live:'Screen coach', settings:'Settings', detail:'Review'};
function node(tag, text='', className='') { const n = document.createElement(tag); if (text !== '') n.textContent = text; if(className) n.className=className; return n; }
function button(text, fn, className='button secondary') { const n=node('button',text,className); n.type='button'; n.addEventListener('click',fn); return n; }
function hide(id, yes=true) { $(id).classList.toggle('hidden',yes); }
function toast(message) { $('toast').textContent=message; hide('toast',false); clearTimeout(toast.timeout); toast.timeout=setTimeout(()=>hide('toast'),5000); }
function error(message) { $('global-error').textContent=message; hide('global-error',false); }
function timeLabel(seconds) { const s=Math.max(0,Math.floor(seconds||0)); return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; }
function dateLabel(value) { return new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}); }
async function api(path, data, options={}) {
  const headers = {'X-NextPlay-Token':state.token,...(options.headers||{})};
  const config = {...options, headers};
  if (data !== undefined) { config.method='POST'; config.body=JSON.stringify(data); headers['Content-Type']='application/json'; }
  const response=await fetch(path,config);
  const result=await response.json();
  if(!response.ok) throw new Error(result.error||'The request could not be completed.');
  return result;
}
function view(name) { state.view=name; document.querySelectorAll('.view').forEach(n=>n.classList.add('hidden')); hide('view-'+name,false); $('page-label').textContent=labels[name]; document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name)); window.scrollTo({top:0,behavior:'instant'}); }
function renderStatus(status) {
  state.status=status;
  const ready=status.key_available&&status.openai_available&&status.tools.ffmpeg&&status.tools.ffprobe;
  $('connection').textContent=ready?'● Ready on your Mac':'Setup needs attention'; $('connection').className='pill'+(ready?'':' error');
  const {player,review}=status.api;
  $('player-name').textContent=player.name||'Your Clash player'; $('player-tag').textContent=player.tag||'Refresh match data in Settings'; $('player-trophies').textContent=player.trophies?.toLocaleString()||'—';
  $('metric-games').textContent=review.history_size??'—'; $('metric-win').textContent=review.overall?.win_rate!=null?review.overall.win_rate+'%':'—';
  $('metric-record').textContent=review.overall?`${review.overall.wins} wins · ${review.overall.losses} losses`:'No match history available';
  $('metric-recent').textContent=review.recent_form?`${review.recent_form.wins}W / ${review.recent_form.losses}L`:'—';
  const modes=Object.keys(review.mode_stats||{}); $('metric-mode').textContent=modes.length===1?(modes[0].toLowerCase().includes('draft')?'Mega Draft sample':'One recorded mode'):`${modes.length} recorded modes`;
  $('result-strip').replaceChildren(...(review.battles||[]).slice(0,10).reverse().map(b=>{const n=node('i',b.result==='WIN'?'W':b.result==='LOSS'?'L':'D',b.result==='WIN'?'win':b.result==='LOSS'?'loss':'');n.title=`${b.result} against ${b.opponent}`;return n;}));
  $('inbox-path').textContent=status.inbox; $('watch-status').textContent=status.settings.watch_enabled?'● Watching inbox':'Inbox paused';
  const selected=$('battle-select').value;
  $('battle-select').replaceChildren(node('option','Use recording evidence only'));
  $('battle-select').firstChild.value='';
  (review.battles||[]).slice(0,30).forEach(b=>{const option=node('option',`${b.result} ${b.your_crowns}–${b.opponent_crowns} vs ${b.opponent} · ${b.time}`);option.value=b.time;$('battle-select').append(option);});
  $('battle-select').value=selected;
  if(document.activeElement?.closest('#settings-form')===null) {
    Object.entries(status.settings).forEach(([key,value])=>{const control=$('settings-form').elements.namedItem(key);if(control){if(control.type==='checkbox')control.checked=value;else control.value=value;}});
  }
  const checks=[['Existing OpenAI key',status.key_available],['AI connection library',status.openai_available],['Recording decoder',status.tools.ffmpeg&&status.tools.ffprobe]];
  $('diagnostics').replaceChildren(...checks.map(([label,ok])=>{const n=node('div','','diagnostic');n.append(node('span',label),node('span',ok?'Ready':'Unavailable',ok?'good':'bad'));return n;}));
  const refresh=status.api.last_refresh;
  $('api-refresh-status').textContent=refresh?refresh.state==='failed'?refresh.error:`Match refresh: ${refresh.state} · ${dateLabel(refresh.time)}${refresh.state==='completed'&&!refresh.new_coaching?' · No new AI review needed.':''}`:'Showing saved match history. Refresh when you want the latest data.';
  $('refresh-api').disabled=['running','queued'].includes(refresh?.state);
  if(status.watch_error?.error) error('Recording inbox: '+status.watch_error.error);
}
function jobRow(job) {
  const row=node('button','','job-row'); row.type='button'; row.addEventListener('click',()=>openJob(job.id));
  const icon=node('div',job.kind==='live'?'◉':'▣','job-icon'); const copy=node('div','','job-copy'); copy.append(node('strong',(job.demo?'[Test footage] ':'')+job.name),node('small',`${dateLabel(job.created)} · ${job.message||job.state}`));
  const status=node('span',job.state==='completed'?'Review ready':job.state==='processing'?`${job.progress}% · Reviewing`:job.state==='monitoring'?'Screen session':job.state,'pill'+(['failed','interrupted','cancelled'].includes(job.state)?' warn':''));
  row.append(icon,copy,status,node('span','↗','arrow')); return row;
}
function renderJobs(jobs) {
  state.jobs=jobs.filter(j=>j.state!=='deleted');
  $('library-count').textContent=state.jobs.filter(j=>!j.demo).length;
  $('metric-reviews').textContent=state.jobs.filter(j=>j.state==='completed'&&!j.demo).length;
  for(const [target,limit] of [['recent-jobs',3],['library-jobs',100]]) { const items=state.jobs.slice(0,limit); $(target).replaceChildren(...(items.length?items.map(jobRow):[node('div','Your first recording review will appear here. Upload footage or start a screen session.','empty-state')])); }
  if(state.selected&&state.view==='detail') { const job=state.jobs.find(j=>j.id===state.selected); if(job&&job.updated!==state.detailUpdated&&!$('detail-content').querySelector('textarea:focus')) renderDetail(job); }
  if(state.liveId) {
    const job=state.jobs.find(j=>j.id===state.liveId);
    if(job) {
      $('live-detail').textContent=job.error||job.message;
      $('live-status').textContent=job.state==='completed'?'Session complete':job.state==='failed'?'Review paused':'● Sharing gameplay';
      if(job.result?.coaching) renderLiveResult(job);
      if(['completed','failed','cancelled','interrupted'].includes(job.state)&&state.stream) stopLive(false).catch(e=>error(e.message));
    }
  }
}
function coachingPanel(report) {
  const panel=node('article','','panel');panel.append(node('div','YOUR NEXT PLAY','section-kicker'),node('h2','A plan grounded in the footage.'),node('p',report.coaching.summary));
  if(!report.coaching.priorities.length) panel.append(node('div',report.provenance?.processing_mode==='local'?'Local recognition supplies card matches and unit predictions. Verify uncertain detections before drawing tactical conclusions.':'No tactical advice was generated from unsupported footage. Try a clearer, full-arena recording.','notice'));
  report.coaching.priorities.forEach((p,i)=>{const card=node('article','','priority');card.append(node('h3',`${i+1}. ${p.title}`),node('span','PRACTICE GOAL','label'),node('p',p.goal),node('span','MEASURE IT','label'),node('p',p.measurement),node('span','QUESTION TO INVESTIGATE','label'),node('p',p.review_question),node('span','EVIDENCE: '+p.evidence_ids.join(', '),'evidence-tag'));panel.append(card);});
  panel.append(node('div',(report.provenance?.processing_mode==='local'?'Local evidence · $0 API cost · ':'AI-reviewed observations · ')+report.coaching.confidence.toLowerCase()+' confidence · Check the screenshots yourself.','quiet-note')); return panel;
}
function seekFrame(job,frame) {
  const video=$('review-video');
  if(video&&job.kind==='video') { video.currentTime=frame.time_seconds; video.scrollIntoView({behavior:'smooth',block:'center'}); video.play().catch(()=>{}); }
  else window.open(`/frames/${job.id}/${frame.id}.jpg`,'_blank','noopener');
}
function evidencePanel(job) {
  const report=job.result;
  const panel=node('article','','panel');panel.append(node('div','SEE WHAT THE COACH SAW','section-kicker'),node('h2','Screenshot evidence'));
  if(report.evaluation){const e=report.evaluation;const box=node('article','','notice');box.append(node('h3','Local good / bad outcome review'),node('p',`${e.counts.favorable||0} favorable · ${e.counts.unfavorable||0} unfavorable damage events · $0 API fee`),node('p','These labels grade tower damage outcomes. They do not prove a good decision or a mistake. Unsupported plays stay ungraded.'));if(!e.events.length)box.append(node('p','No damage event passed the evidence checks.'));e.events.forEach(o=>{const b=button(`${o.sample_start_seconds.toFixed(1)}–${o.end_seconds.toFixed(1)}s · ${o.statement}`,()=>{const v=$('review-video');if(v){v.currentTime=o.sample_start_seconds;v.scrollIntoView({block:'center'});}});box.append(b);});panel.append(box);}
  if(report.recognition){const r=report.recognition;const summary=node('article','','notice');summary.append(node('h3','Recognition on this Mac'),node('p',`${r.card_names.length} card identities · ${(r.hand_coverage*100).toFixed(1)}% of hand slots matched · $0 API fee`),node('p','Hand coverage is not accuracy. Arena predictions are experimental; newer cards and evolutions may remain unknown.'),node('p','Cards: '+r.card_names.join(', ')),node('p','Repeated unit candidates: '+(r.object_labels.join(', ')||'none passed the threshold')));panel.append(summary);}
  const frames=Object.fromEntries(report.frames.map(f=>[f.id,f]));
  if(!report.observations.length) panel.append(node('p','The sampled frames did not establish sufficiently clear gameplay observations. No mistakes were invented.'));
  const list=node('div','','evidence-list');
  report.observations.forEach(o=>{
    const frame=frames[o.frame_ids[0]];if(!frame)return;
    const card=node('article','','evidence-card');const img=node('img','','frame-thumb');img.src=`/frames/${job.id}/${frame.id}${frame.overlay?'-overlay':''}.jpg`;img.alt='Screenshot evidence at '+timeLabel(frame.time_seconds);img.loading='lazy';img.addEventListener('click',()=>seekFrame(job,frame));
    const copy=node('div');copy.append(button('Sample '+timeLabel(o.sample_start_seconds),()=>seekFrame(job,frame),'sample-button'),node('h3',o.statement),node('p',o.visible_evidence),node('span',`${o.confidence} CONFIDENCE · ${report.provenance?.processing_mode==='local'?'LOCAL / UNVERIFIED':'AI REVIEWED'} · ${o.id}`,'evidence-tag'));if(frame.overlay)copy.append(button('Inspect annotated screenshot',()=>window.open(`/frames/${job.id}/${frame.id}-overlay.jpg`,'_blank','noopener'),'button secondary'));card.append(img,copy);list.append(card);
  });panel.append(list);
  const strip=node('div','','frame-strip');report.frames.forEach(f=>{const img=node('img');img.src=`/frames/${job.id}/${f.id}.jpg`;img.alt='Sample '+timeLabel(f.time_seconds);img.title=img.alt;img.loading='lazy';img.addEventListener('click',()=>seekFrame(job,f));strip.append(img);});panel.append(node('p','Sampled frames · events between samples remain unknown.','quiet-note'),strip);
  return panel;
}
async function openJob(id) { state.selected=id; state.detailUpdated=null; view('detail'); const job=await api('/api/jobs/'+id);renderDetail(job); }
function renderDetail(job) {
  state.detailUpdated=job.updated;
  const root=$('detail-content');root.replaceChildren();
  const heading=node('div','','detail-heading');const title=node('div');title.append(node('div',job.kind==='live'?'SCREEN SESSION':'RECORDING REVIEW','eyebrow'),node('h1',job.name),node('p',dateLabel(job.created)+' · '+job.state));const actions=node('div','','detail-actions');
  if(job.result?.coaching) { actions.append(button('Export Markdown',()=>download(job.id,'md')),button('Export JSON',()=>download(job.id,'json'))); }
  if(['failed','interrupted','cancelled'].includes(job.state)&&job.kind==='video') actions.append(button('Retry review',()=>jobAction(job.id,'retry'),'button primary'));
  if(['queued','processing','monitoring'].includes(job.state)) actions.append(button(job.kind==='live'?'Stop session':'Cancel review',()=>jobAction(job.id,'cancel'),'button danger'));
  else actions.append(button('Delete local copy',async()=>{if(confirm('Delete the local recording copy, evidence, notes, and report? Your original inbox file is kept.')){await jobAction(job.id,'delete');state.selected=null;view('library');}},'button danger'));
  heading.append(title,actions);root.append(heading);
  if(job.demo)root.append(node('div','TEST FOOTAGE — this validates the system and is not your gameplay or player evidence.','notice demo'));
  if(job.error)root.append(node('div',job.error,'notice error'));
  if(job.result?.coaching && job.state!=='completed' && job.kind==='video')root.append(node('div','Showing the previous saved report while this review is retried. It is not the result of the current attempt.','notice'));
  if(!job.result?.coaching) { const panel=node('article','','panel job-status-panel');panel.append(node('h2',job.state==='failed'?'This review needs attention.':job.state==='interrupted'?'Review interrupted.':job.state==='cancelled'?'Review cancelled.':job.state==='completed'?'No screenshot evidence to review.':'Your review is in progress.'),node('p',job.message));const track=node('div','','progress-track');const fill=node('i');fill.style.width=job.progress+'%';track.append(fill);panel.append(track);root.append(panel);return; }
  const report=job.result;const grid=node('div','','detail-grid');const left=node('div');
  if(job.kind==='video'){const panel=node('article','','panel');const video=node('video','','review-video');video.id='review-video';video.controls=true;video.playsInline=true;video.preload='metadata';video.src='/media/'+job.id;video.addEventListener('error',()=>toast('Playback is unavailable in this browser. Your sampled screenshots and report are still accessible.'));panel.append(video,node('p',`Recording length ${timeLabel(report.video.duration_seconds)} · ${report.frames.length} sampled frames · maximum gap ${(report.video.sampling_gap_seconds||0).toFixed(1)}s`,'quiet-note'));left.append(panel);}
  left.append(evidencePanel(job));grid.append(left,coachingPanel(report));root.append(grid);
  const limits=node('article','','panel');limits.style.marginTop='22px';limits.append(node('h2','What remains unknown'));const list=node('ul','','detail-limits');[...report.unknowns,...report.data_limits].forEach(x=>list.append(node('li',x)));limits.append(list);root.append(limits);
  const notePanel=node('article','','panel');notePanel.style.marginTop='22px';notePanel.append(node('h2','Your review notes'),node('p','Record what you checked at full speed and what you want to practice next. These notes stay on your Mac.'));const textarea=node('textarea','','notes');textarea.value=job.notes||'';textarea.setAttribute('aria-label','Your review notes');notePanel.append(textarea,button('Save notes',async()=>{await api(`/api/jobs/${job.id}/notes`,{text:textarea.value});toast('Notes saved.');}));root.append(notePanel);
}
function renderLiveResult(job) {
  if($('live-results').dataset.updated===job.updated)return;
  $('live-results').dataset.updated=job.updated;$('live-results').replaceChildren(coachingPanel(job.result),button('Open screenshots and full report',()=>openJob(job.id),'button secondary'));
}
async function jobAction(id,action) {try{await api(`/api/jobs/${id}/${action}`,{});await poll();toast(action==='retry'?'Review queued.':action==='delete'?'Local copy deleted.':'Review stopped.');}catch(e){error(e.message);}}
async function download(id,ext) {try{const response=await fetch(`/reports/${id}.${ext}`,{headers:{'X-NextPlay-Token':state.token}});if(!response.ok)throw new Error('Report not available.');const blob=await response.blob();const url=URL.createObjectURL(blob);const a=node('a');a.href=url;a.download=`nextplay-${id.slice(0,8)}.${ext}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}catch(e){error(e.message);}}
async function upload(file) {
  if(!file||state.uploadBusy)return;
  const limit=(state.status?.settings.max_upload_mb||2048)*1024*1024;
  if(file.size>limit){error(`This recording is ${(file.size/1024/1024).toFixed(0)} MB; the upload limit is ${state.status?.settings.max_upload_mb||2048} MB. Duration is checked separately. For larger files, use the recording inbox or compress the video.`);return;}
  if(!/\.(mp4|mov|m4v|webm|mkv)$/i.test(file.name)){error('Choose an MP4, MOV, M4V, WebM, or MKV recording.');return;}
  state.uploadBusy=true;hide('upload-progress',false);hide('global-error');$('upload-bar').style.width='0%';$('upload-status').textContent='Uploading '+file.name;
  try {
    const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/uploads');xhr.setRequestHeader('X-NextPlay-Token',state.token);xhr.setRequestHeader('X-File-Name',encodeURIComponent(file.name));xhr.setRequestHeader('Content-Type','application/octet-stream');if($('battle-select').value)xhr.setRequestHeader('X-Battle-Time',$('battle-select').value);xhr.upload.onprogress=e=>{if(e.lengthComputable){const percent=Math.round(e.loaded/e.total*100);$('upload-bar').style.width=percent+'%';$('upload-status').textContent=percent===100?'Upload received. Preparing your review…':`Uploading · ${percent}%`;}};xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);xhr.status<300?resolve(data):reject(new Error(data.error||'Upload failed.'));}catch{reject(new Error('Upload interrupted. Try again.'));}};xhr.onerror=()=>reject(new Error('Could not reach NextPlay. Check that the local app is running.'));xhr.send(file);});
    toast(result.duplicate?'This recording is already in your library.':'Recording added. Your review is queued.');await poll();await openJob(result.job.id);
  }catch(e){error(e.message);}finally{state.uploadBusy=false;hide('upload-progress');$('file-input').value='';}
}
async function startLive() {
  if(!navigator.mediaDevices?.getDisplayMedia){error('This browser does not support screen sharing. Open http://127.0.0.1:8777 in Chrome, Edge, or Safari.');return;}
  $('start-live').disabled=true;hide('global-error');
  try {
    state.stream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:5},audio:false});
    const result=await api('/api/live/start',{battle_time:$('battle-select').value||null});state.liveId=result.job.id;state.stopping=false;
    $('live-results').dataset.updated='';$('live-results').replaceChildren(node('div','New screen session started. Collecting the first batch of evidence.','empty-state'));
    const video=$('live-preview');video.srcObject=state.stream;await video.play();
    state.stream.getVideoTracks()[0].addEventListener('ended',()=>stopLive().catch(e=>error(e.message)),{once:true});
    hide('live-empty');hide('start-live');hide('stop-live',false);$('live-status').textContent='● Sharing gameplay';
    $('live-detail').textContent='Saving screenshot samples. Feedback arrives when the first batch finishes.';
    state.timer=setInterval(sendFrame,(state.status?.settings.live_interval||5)*1000);await sendFrame();await poll();
  }catch(e){if(state.stream)state.stream.getTracks().forEach(t=>t.stop());state.stream=null;error(e.name==='NotAllowedError'?'Screen sharing was not started. Press Start when you are ready to select the gameplay window.':e.message);}
  finally{$('start-live').disabled=false;}
}
async function sendFrame() {
  if(!state.stream||!state.liveId||state.sending)return;
  state.sending=true;
  try {
    const video=$('live-preview');if(!video.videoWidth)return;
    if(!sendFrame.started)sendFrame.started=performance.now();
    const canvas=document.createElement('canvas');const scale=Math.min(1,1280/Math.max(video.videoWidth,video.videoHeight));canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.82));
    const response=await fetch(`/api/live/${state.liveId}/frame`,{method:'POST',headers:{'X-NextPlay-Token':state.token,'X-Sample-Time':String((performance.now()-sendFrame.started)/1000),'Content-Type':'image/jpeg'},body:blob});
    const result=await response.json();if(!response.ok)throw new Error(result.error);
    $('live-detail').textContent=result.accepted?'Screenshot saved. The next evidence check will appear automatically.':result.reason;
  }catch(e){error(e.message);await stopLive(false);}finally{state.sending=false;}
}
async function stopLive(notify=true) {
  if(state.stopping)return;state.stopping=true;clearInterval(state.timer);state.timer=null;
  const stream=state.stream;state.stream=null;if(stream)stream.getTracks().forEach(t=>t.stop());$('live-preview').srcObject=null;sendFrame.started=null;hide('live-empty',false);hide('start-live',false);hide('stop-live');$('live-status').textContent='Not sharing';
  if(state.liveId&&notify){try{await api(`/api/live/${state.liveId}/stop`,{});}catch(e){error(e.message);}}
  state.stopping=false;
}
async function poll() {const [status,jobs]=await Promise.all([api('/api/status'),api('/api/jobs')]);renderStatus(status);renderJobs(jobs.jobs);}
async function init() {
  document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>view(n.dataset.view)));
  $('open-live').onclick=()=>view('live');$('all-reviews').onclick=()=>view('library');$('back-library').onclick=()=>view('library');$('upload-library').onclick=()=>{view('home');$('file-input').click();};
  $('dropzone').onclick=()=>$('file-input').click();$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('file-input').click();}};
  $('file-input').onchange=e=>upload(e.target.files[0]);
  for(const event of ['dragenter','dragover'])$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.add('dragover');});
  for(const event of ['dragleave','drop'])$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.remove('dragover');});
  $('dropzone').addEventListener('drop',e=>upload(e.dataTransfer.files[0]));
  const playerStatus=async()=>{try{const s=await api('/api/player/status');$('player-status').textContent=(s.running?'Running':'Stopped')+' · '+JSON.stringify(s.last)+' · Screen access: '+(s.permissions.screen_permission?'ready':'missing')+' · Input access: '+(s.permissions.input_permission?'ready':'missing');}catch(e){$('player-status').textContent=e.message;}};
  $('player-check').onclick=playerStatus;
  for(const [id,control] of [['player-shadow',false],['player-start',true]])$(id).onclick=async()=>{try{await api('/api/player/start',{control});await playerStatus();}catch(e){$('player-status').textContent=e.message;}};
  $('player-stop').onclick=async()=>{try{await api('/api/player/stop',{});await playerStatus();}catch(e){$('player-status').textContent=e.message;}};
  setInterval(()=>{if(state.view==='live')playerStatus();},2000);
  $('start-live').onclick=startLive;$('stop-live').onclick=()=>stopLive().catch(e=>error(e.message));
  $('refresh-api').onclick=async()=>{try{await api('/api/refresh',{});toast('Refreshing official match data.');await poll();}catch(e){error(e.message);}};
  $('settings-form').onsubmit=async e=>{e.preventDefault();const values={};const form=$('settings-form');for(const control of form.elements){if(!control.name)continue;values[control.name]=control.type==='checkbox'?control.checked:control.type==='number'?Number(control.value):control.value.trim();}try{await api('/api/settings',values);$('settings-status').textContent='Settings saved. Active reviews keep their original limits.';await poll();}catch(e){error(e.message);}};
  window.addEventListener('pagehide',()=>{if(state.stream)state.stream.getTracks().forEach(t=>t.stop());fetch('/api/player/stop',{method:'POST',headers:{'X-NextPlay-Token':state.token,'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});if(state.liveId)fetch(`/api/live/${state.liveId}/stop`,{method:'POST',headers:{'X-NextPlay-Token':state.token,'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});});
  try{const boot=await fetch('/api/bootstrap');const data=await boot.json();if(!boot.ok)throw new Error(data.error);state.token=data.token;await poll();setInterval(()=>poll().catch(e=>{$('connection').textContent='App disconnected';$('connection').className='pill error';error(e.message);}),4000);}catch(e){error('Could not connect to NextPlay. '+e.message);}
}
init();
