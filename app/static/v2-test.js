'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const csrf=document.querySelector('meta[name="csrf-token"]').content;
const analyst=document.body.dataset.role==='analyst';
const state={snapshot:null,caseId:null,physicalId:null,visitId:null,projectId:null,segment:null,analysis:null,interview:null,clip:null,stream:null,recorder:null,recording:false,timer:null,objectURL:null,queue:Promise.resolve(),pending:0,unsaved:[],lastAnalysisAt:0,pendingFollowUp:null};
const root=()=>'/api/v1/cases/'+encodeURIComponent(state.caseId);
const uid=()=>crypto.randomUUID();
function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
async function api(url,{method='GET',body,form=false,key=uid()}={}){
 const headers={};if(method!=='GET'){headers['X-CSRF-Token']=csrf;headers['Idempotency-Key']=key;}
 if(body&&!form){headers['Content-Type']='application/json';body=JSON.stringify(body);}
 const response=await fetch(url,{method,headers,body,credentials:'same-origin'});
 if(!response.ok){let detail=response.statusText;try{detail=(await response.json()).detail;}catch{}throw new Error(typeof detail==='string'?detail:JSON.stringify(detail));}
 return response.status===204?null:response.json();
}
async function action(fn){try{await fn();}catch(error){message(error.message,true);}}
function options(element,items,label,selected){element.innerHTML=items.map(item=>`<option value="${esc(item.id)}">${esc(label(item))}</option>`).join('');if(items.some(i=>i.id===selected))element.value=selected;}
async function load(){
 const cases=await api('/api/v1/cases');options($('case'),cases,c=>c.company,state.caseId);
 if(!cases.length){message('No V2 demonstration case has been prepared yet. Existing V1 inspections remain available.');return;}
 state.caseId=$('case').value;state.snapshot=await api(root()+'/export');
 const visits=state.snapshot.v1_inspections.map(v=>v.inspection);options($('visit'),visits,v=>v.name,state.visitId||visits.at(-1)?.id);state.visitId=$('visit').value;
 await selectVisit();
 const caps=await api('/api/v1/capabilities');$('capabilities').textContent=`AI: ${caps.groq_configured?'configured; actual requests will be checked':'key not configured'} · Audio decoder: ${caps.audio_decode_available?'available':'unavailable'} · Speech uses short clips · Email goes to a local test inbox.`;
 options($('reviewer'),caps.analyst_actors.map(a=>({id:a})),a=>a.id,document.body.dataset.actor);
 message('Saved case history loaded. Forecasts and recordings do not establish commissioning.');
}
async function selectVisit(){
 state.visitId=$('visit').value;state.segment=null;state.interview=null;
 const bound=new Set(state.snapshot.asset_bindings.filter(b=>b.active&&b.inspection_id===state.visitId).map(b=>b.physical_asset_id));
 const machines=state.snapshot.physical_assets.filter(a=>bound.has(a.id));options($('machine'),machines,a=>a.label+' · '+a.serial,state.physicalId);state.physicalId=$('machine').value||null;
 selectMachine();
}
function selectMachine(){
 state.physicalId=$('machine').value||null;state.interview=null;state.segment=null;
 const projects=state.snapshot.investments.filter(p=>p.asset_links.some(a=>a.physical_asset_id===state.physicalId));
 options($('project'),projects,p=>p.title,state.projectId);state.projectId=$('project').value||null;
 render();
}
function render(){
 const s=state.snapshot;if(!s)return;
 const p=s.investments.find(p=>p.id===state.projectId),targets=s.targets.filter(t=>t.project_id===p?.id);
 $('history').innerHTML=(p?`<p><strong>${esc(p.title)}</strong> · ${esc(p.stage)}</p><p>${esc(p.rationale)}</p><p>Proposed: ${esc(p.proposed_amount??'unknown')} ${esc(p.currency??'')} · Reported proposal</p>`:'<p>No investment is linked to this machine.</p>')+targets.map(t=>`<p>Forecast: ${esc(t.metric)} ${esc(t.target_type)} ${esc(t.target_value)} ${esc(t.unit)} · Baseline: ${esc(t.baseline_value??'unknown')} · Outcome: ${esc(s.investment_reviews.filter(r=>r.target_id===t.id).at(-1)?.status??'not yet measurable')}</p>`).join('');
 const visit=s.v1_inspections.find(v=>v.inspection.id===state.visitId),binding=s.asset_bindings.find(b=>b.active&&b.inspection_id===state.visitId&&b.physical_asset_id===state.physicalId);
 const claims=visit?.claims.filter(c=>c.asset_id===binding?.local_asset_id)||[];
 $('task-claim').innerHTML='<option value="">Project/asset verification requirement</option>'+claims.map(c=>`<option value="${esc(c.id)}">${esc(c.kind)}</option>`).join('');
 const tasks=s.follow_ups.filter(f=>f.details.physical_asset_id===state.physicalId);
 $('tasks').innerHTML=tasks.map(f=>`<div class="card"><strong>${esc(f.task.request)}</strong><p>${esc(f.details.workflow_status)} · Due ${esc(f.details.due_date)} · Reviewer ${esc(f.details.reviewer)}</p><p>Required: ${esc(f.details.required_evidence)}</p></div>`).join('')||'<p>No enhanced follow-ups for this machine.</p>';
 const recordings=s.audio.filter(a=>a.physical_asset_id===state.physicalId);
 $('recordings').innerHTML=recordings.map(a=>`<div class="card"><p>${esc(a.capture_type)} · ${esc(a.duration_seconds)} seconds · ${esc(a.note)}</p><p class="tag">${esc(a.quality_flags.join(', ')||'No signal-quality warning')} · ${a.synthetic?'Synthetic demo':'Restricted source'}</p><audio controls preload="none" src="${root()}/audio/${encodeURIComponent(a.id)}/original"></audio>${analyst&&a.capture_type!=='machine_acoustic'?`<button type="button" data-transcribe="${esc(a.id)}">Transcribe and translate this clip</button>`:''}</div>`).join('')||'<p>No recordings yet.</p>';
 const machineClips=recordings.filter(a=>a.capture_type==='machine_acoustic');options($('compare-first'),machineClips,a=>a.filename+' · '+a.created_at,machineClips[0]?.id);options($('compare-second'),machineClips,a=>a.filename+' · '+a.created_at,machineClips.at(-1)?.id);
 $('pdf').href=root()+'/report.pdf';$('json').href=root()+'/export';
 if(!analyst)document.querySelectorAll('button:not(#refresh),form').forEach(el=>{el.disabled=true;if(el.tagName==='FORM')el.hidden=true;});
}
async function refresh(){state.snapshot=await api(root()+'/export');render();}
function requireContext(){if(!state.physicalId||!state.visitId)throw new Error('Select a machine with confirmed identity in this visit first.');}
async function getInterview(){
 requireContext();if(state.interview)return state.interview;
 if(!$('consent').checked)throw new Error('Confirm interview/recording authorization first.');
 state.interview=await api(root()+'/interviews',{method:'POST',body:{inspection_id:state.visitId,physical_asset_id:state.physicalId,project_id:state.projectId,speaker_label:$('speaker').value,speaker_confirmed:$('speaker-confirmed').checked,consent_confirmed:true,consent_note:'Analyst confirmed authorization in the verification workspace',synthetic:$('synthetic').checked,reason:'Begin source-linked inspection interview'}});
 return state.interview;
}
function clipMetadata(){return {inspection_id:state.visitId,physical_asset_id:state.physicalId,capture_type:$('capture-type').value,captured_at:new Date().toISOString(),device:$('device').value,operating_mode:$('operating-mode').value,note:$('audio-note').value,consent_confirmed:$('consent').checked,consent_note:'Analyst confirmed recording authorization and informed speakers',synthetic:$('synthetic').checked,share_with_judges:$('share').checked,signal_processing:$('capture-type').value==='machine_acoustic'?'none_requested':'speech_enhancement',reason:'Save original recording and capture conditions'};}
async function saveClip(clip){
 if(clip.saved)return clip.saved;
 const form=new FormData();form.append('file',new File([clip.blob],clip.filename,{type:clip.blob.type}));form.append('metadata',JSON.stringify(clip.metadata));
 clip.saved=await api('/api/v1/cases/'+encodeURIComponent(clip.caseId)+'/audio',{method:'POST',body:form,form:true,key:clip.key});
 state.unsaved=state.unsaved.filter(c=>c.key!==clip.key);renderUnsaved();
 return clip.saved;
}
function localClip(blob,metadata){
 const extension=blob.type.includes('webm')?'webm':blob.type.includes('wav')?'wav':'m4a';
 const clip={blob,metadata,caseId:state.caseId,filename:'inspection-'+Date.now()+'.'+extension,key:uid(),saved:null};
 state.clip=clip;state.unsaved.push(clip);renderUnsaved();if(state.objectURL)URL.revokeObjectURL(state.objectURL);state.objectURL=URL.createObjectURL(blob);$('preview').src=state.objectURL;$('save-audio').disabled=false;return clip;
}
function renderUnsaved(){$('unsaved-clips').innerHTML=state.unsaved.map(c=>`<p class="muted">Unsaved original: ${esc(c.filename)} <button type="button" data-retry="${esc(c.key)}">Retry save</button> <button type="button" data-download="${esc(c.key)}">Download local copy</button></p>`).join('');}
function lockCapture(value){for(const id of ['case','visit','machine','project','capture-type','language','incremental','speaker','speaker-confirmed'])$(id).disabled=value;}
async function transcribe(recording,mode='prerecorded',session=null){
 const interview=session||await getInterview();
 state.segment=await api(root()+'/audio/'+recording.id+'/transcribe',{method:'POST',body:{interview_id:interview.id,language:$('language').value,mode,reason:'Process actual saved interview audio; preserve original and English rendering'}});
 $('transcript').value=state.segment.text;$('translation').textContent=state.segment.english_translation?'English rendering (provider; review before accepting): '+state.segment.english_translation:'';
 message('Transcript saved from actual audio. Review identifiers, amounts and translation before confirming proposals.');
}
async function begin(){
 requireContext();if(!$('consent').checked)throw new Error('Confirm recording authorization first.');
 if(!navigator.mediaDevices?.getUserMedia)throw new Error('Microphone access needs HTTPS or localhost in a supported browser. Use saved-file upload as a fallback.');
 const incremental=$('incremental').checked;if(incremental&&$('capture-type').value==='machine_acoustic')throw new Error('Incremental speech processing requires Interview speech or Inspector voice note mode.');
 const session=incremental?await getInterview():null;
 const speech=$('capture-type').value!=='machine_acoustic';
 state.stream=await navigator.mediaDevices.getUserMedia({audio:speech?true:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
 state.recording=true;lockCapture(true);$('record').disabled=true;$('stop').disabled=false;$('record-state').textContent='Recording. Nothing is marked saved until the server confirms persistence.';
 const recordingContext={caseId:state.caseId,visitId:state.visitId,physicalId:state.physicalId};
 function next(){
  if(!state.recording)return;
  const type=['audio/webm;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));if(!type)throw new Error('No supported recorder codec; use saved-file upload.');
  const recorder=new MediaRecorder(state.stream,{mimeType:type});state.recorder=recorder;const chunks=[];const metadata=clipMetadata();
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  recorder.onstop=()=>{
   clearTimeout(state.timer);const blob=new Blob(chunks,{type:recorder.mimeType});const clip=localClip(blob,metadata);clip.caseId=recordingContext.caseId;
   if(incremental){
    state.pending++;
    state.queue=state.queue.then(async()=>{const saved=await saveClip(clip);await transcribe(saved,'microphone_chunk',session);await refresh();if(Date.now()-state.lastAnalysisAt>30000)await generateAnalysis();}).catch(error=>{stop();message(error.message+(clip.saved?' The original audio is saved; speech processing was interrupted.':' Capture stopped. Keep this page open to retry or download the unsaved original.'),true);}).finally(()=>{state.pending--;$('record-state').textContent=state.recording?`Recording; ${state.pending} clip(s) processing`:'Stopped. Saved clips remain in history; unsaved clips need retry.';});
    if(state.pending>=3){stop();message('Capture paused because speech processing is behind. Saved recordings are retained; let processing finish before continuing.',true);}else if(state.recording){next();}
   }else{state.recording=false;lockCapture(false);state.stream.getTracks().forEach(t=>t.stop());$('record').disabled=false;$('stop').disabled=true;$('record-state').textContent='Stopped. Preview is local and unsaved. Choose Save clip.';}
  };
  recorder.start();state.timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},incremental?8000:110000);
 }
 next();
}
function stop(){state.recording=false;lockCapture(false);clearTimeout(state.timer);if(state.recorder?.state==='recording')state.recorder.stop();state.stream?.getTracks().forEach(t=>t.stop());$('record').disabled=false;$('stop').disabled=true;}
async function generateAnalysis(){if(!state.segment)throw new Error('Save or transcribe a source segment first.');state.lastAnalysisAt=Date.now();const analysis=await api(root()+'/segments/'+state.segment.id+'/analyse',{method:'POST',body:{reason:'Suggest source-linked inspection questions and editable candidates',allow_rule_fallback:$('fallback').checked}});showAnalysis(analysis,await api(root()+'/candidates'));message('Questions and proposals saved. Review each source before accepting.');}
function showAnalysis(analysis,candidates){
 state.analysis=analysis;$('questions').innerHTML=`<p class="tag">${esc(analysis.provider)} · ${esc(analysis.model)} ${esc(analysis.notices.join(' '))}</p>`+analysis.questions.map((q,i)=>`<div class="card"><strong>${esc(q.question)}</strong><p>${esc(q.why)}</p><p>Requested support: ${esc(q.proposed_evidence)}</p><button type="button" data-question="${i}" data-status="asked">Mark asked</button> <button type="button" data-question="${i}" data-status="dismissed">Dismiss</button></div>`).join('');
 $('candidates').innerHTML=candidates.filter(c=>analysis.candidate_ids.includes(c.id)).map(c=>`<form class="card candidate" data-id="${esc(c.id)}"><h3>${esc(c.payload.kind)} · ${esc(c.review_status)}</h3><p>Source quote: ${esc(c.payload.quote)}</p><label>Proposed text<textarea name="text">${esc(c.payload.text)}</textarea></label><div class="grid"><label>Value<input name="value" type="number" step="any" value="${esc(c.payload.value??'')}"></label><label>Unit<input name="unit" value="${esc(c.payload.unit??'')}"></label><label>Due date, only if confirmed<input name="due_date" type="date" value="${esc(c.payload.due_date??'')}"></label><label>Currency<input name="currency" value="${esc(c.payload.currency??'')}"></label></div><label class="check"><input name="confirmed" type="checkbox" required>I reviewed the original source and numerical/date interpretation. Acceptance records a report or forecast, not verified fact.</label><button type="submit" ${c.review_status!=='pending'?'disabled':''}>Save reviewed proposal</button></form>`).join('')||'<p>No candidate records proposed. You can create a project or follow-up manually.</p>';
 state.candidates=candidates;
}
$('refresh').onclick=()=>action(load);
$('case').onchange=()=>action(async()=>{state.caseId=$('case').value;state.visitId=null;state.physicalId=null;await load();});
$('visit').onchange=()=>action(selectVisit);$('machine').onchange=selectMachine;$('project').onchange=()=>{state.projectId=$('project').value||null;state.interview=null;render();};
$('record').onclick=()=>action(begin);$('stop').onclick=stop;
$('save-audio').onclick=()=>action(async()=>{if(!state.clip)throw new Error('Record or select a file first.');await saveClip(state.clip);$('save-audio').disabled=true;message('Original recording saved on the server.');await refresh();});
$('audio-file').onchange=()=>action(async()=>{requireContext();const file=$('audio-file').files[0];if(!file)return;if(file.size>12*1024*1024)throw new Error('File exceeds 12 MiB.');const clip=localClip(file,clipMetadata());clip.filename=file.name;message('File selected locally; it is not saved yet.');});
$('save-photo').onclick=()=>action(async()=>{requireContext();const file=$('photo-file').files[0];if(!file)throw new Error('Choose a phone photo first.');const body=new FormData();for(const [k,v] of Object.entries({kind:'site_image',source:'Analyst phone camera capture',captured_at:new Date().toISOString(),reason:'Save photograph for explicit analyst evidence review'}))body.append(k,v);body.append('file',file);await api('/api/v1/inspections/'+state.visitId+'/evidence',{method:'POST',body,form:true});message('Photo original saved, unaccepted. Review and link it in the existing Evidence screen.');await refresh();});
$('save-segment').onclick=()=>action(async()=>{const interview=await getInterview();state.segment=await api(root()+'/interviews/'+interview.id+'/segments',{method:'POST',body:{text:$('transcript').value,language:$('language').value,mode:$('synthetic').checked?'synthetic_transcript':'manual',reason:'Save original interview text with its source context'}});$('translation').textContent='';message('Original source text saved.');await refresh();});
$('translate').onclick=()=>action(async()=>{if(!state.segment)throw new Error('Save the original Japanese segment first.');state.segment=await api(root()+'/segments/'+state.segment.id+'/translate',{method:'POST',body:{version:state.segment.version,reason:'Request actual provider translation while retaining the original'}});$('translation').textContent='English rendering (provider; review required): '+state.segment.english_translation;await refresh();});
$('analyse').onclick=()=>action(generateAnalysis);
$('recordings').onclick=e=>{const button=e.target.closest('[data-transcribe]');if(button)action(async()=>{const audio=state.snapshot.audio.find(a=>a.id===button.dataset.transcribe);if(audio.inspection_id!==state.visitId)throw new Error('Select the recording’s original visit before transcribing it.');await transcribe(audio);await refresh();});};
$('questions').onclick=e=>{const button=e.target.closest('[data-question]');if(button)action(async()=>{state.analysis=await api(root()+'/analyses/'+state.analysis.id+'/question',{method:'PATCH',body:{version:state.analysis.version,index:Number(button.dataset.question),status:button.dataset.status,reason:'Analyst records question disposition'}});button.disabled=true;message('Question disposition saved.');});};
$('candidates').onsubmit=e=>{e.preventDefault();action(async()=>{const form=e.target,c=state.candidates.find(c=>c.id===form.dataset.id),v=Object.fromEntries(new FormData(form));const edited={...c.payload,text:v.text,value:v.value===''?null:v.value,unit:v.unit||null,currency:v.currency||null,due_date:v.due_date||null};if(c.payload.kind==='follow_up'){state.pendingFollowUp={candidate:c,edited};$('task-form').elements.request.value=edited.text;if(edited.due_date)$('task-form').elements.due_date.value=edited.due_date;$('task-form').closest('details').open=true;$('task-form').scrollIntoView({behavior:'smooth'});message('Complete owner, reviewer and required evidence below, then save to confirm this proposed follow-up.');return;}const p=state.snapshot.investments.find(p=>p.id===state.projectId);await api(root()+'/candidates/'+c.id+'/confirm',{method:'POST',body:{version:c.version,action:'accept',project_id:state.projectId,project_version:p?.version,edited,confirmed_source:form.elements.confirmed.checked,reason:'Analyst reviewed and edited proposal; saved differences retained in audit'}});form.querySelector('button').disabled=true;await refresh();message('Reviewed record saved as reported/forecast. Its edits and source remain in the audit history.');});};
$('project-form').onsubmit=e=>{e.preventDefault();action(async()=>{requireContext();const v=Object.fromEntries(new FormData(e.target));await api(root()+'/investments',{method:'POST',body:{inspection_id:state.visitId,title:v.title,kind:v.kind,rationale:v.rationale,proposed_amount:v.proposed_amount||null,currency:v.proposed_amount?v.currency.toUpperCase():null,asset_links:[{physical_asset_id:state.physicalId,role:'existing'}],source:{kind:'management_report',attribution:$('speaker').value,quote:v.rationale},reason:'Analyst records a management proposal'}});await refresh();selectMachine();message('Reported investment proposal saved.');});};
$('task-form').onsubmit=e=>{e.preventDefault();action(async()=>{requireContext();const v=Object.fromEntries(new FormData(e.target));const followUp={inspection_id:state.visitId,physical_asset_id:state.physicalId,project_id:state.projectId,claim_id:v.claim_id||null,request:v.request,contact:v.contact,reviewer:v.reviewer,due_date:v.due_date,required_evidence:v.required_evidence,verification_method:'document_review',source:{kind:'analyst_observation',attribution:document.body.dataset.actor,quote:v.request},reason:'Assign explicit evidence verification request'};if(state.pendingFollowUp){const {candidate,edited}=state.pendingFollowUp;await api(root()+'/candidates/'+candidate.id+'/confirm',{method:'POST',body:{version:candidate.version,action:'accept',project_id:state.projectId,edited,confirmed_source:true,follow_up:followUp,reason:'Analyst confirms edited follow-up and verification requirements'}});state.pendingFollowUp=null;}else{await api(root()+'/follow-ups',{method:'POST',body:followUp});}await refresh();message('Follow-up saved; closure requires supported verification.');});};
$('compare').onclick=()=>action(async()=>{const result=await api(root()+'/audio-comparisons',{method:'POST',body:{first_id:$('compare-first').value,second_id:$('compare-second').value,reason:'Compare transparent signal features with recorded comparability conditions'}});$('comparison').textContent=result.conclusion+' '+result.warnings.join('; ');await refresh();});
$('reminders').onclick=()=>action(async()=>{const results=await api(root()+'/reminders/run',{method:'POST',body:{reason:'Analyst requests due-date reminder verification in local test inbox'}});message('Reminder results: '+(results.map(r=>r.status).join(', ')||'No request is due.'));});
$('audit').onclick=()=>action(async()=>{$('audit-log').textContent=JSON.stringify(await api(root()+'/activity'),null,2);message('Saved edits show author, reason, time and complete before/after values.');});
$('unsaved-clips').onclick=e=>{const button=e.target.closest('[data-retry],[data-download]');if(!button)return;const clip=state.unsaved.find(c=>c.key===(button.dataset.retry||button.dataset.download));if(!clip)return;if(button.dataset.retry)action(async()=>{await saveClip(clip);await refresh();message('Original clip saved after retry.');});else{const url=URL.createObjectURL(clip.blob),a=document.createElement('a');a.href=url;a.download=clip.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}};
$('speaker').onchange=()=>{state.interview=null;};$('speaker-confirmed').onchange=()=>{state.interview=null;};$('consent').onchange=()=>{if(!$('consent').checked)stop();};
window.addEventListener('beforeunload',e=>{if(state.recording||state.unsaved.length){e.preventDefault();e.returnValue='';}stop();if(state.objectURL)URL.revokeObjectURL(state.objectURL);});
action(load);
