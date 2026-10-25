/* Intake adds reviewed proposals to the existing evidence and registry workflow. */
(() => {
  'use strict';
  const U = window.IntegrityUI;
  const E = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const S = {items: [], selected: null, busy: false};
  const root = () => `/api/v1/inspections/${U.state.iid}`;
  const input = (name, label, value = '', extra = '') => `<label class="v2-field">${E(label)}<input name="${name}" value="${E(value)}" maxlength="200" ${extra}></label>`;
  const fields = ['tag','manufacturer','model','serial','site','rated_power_kw','horse_power','rated_voltage_v','rated_speed_rpm','invoice_ref','payment_ref'];
  const labels = ['Internal tag','Manufacturer','Model','Serial (blank if unknown)','Site association','Power kW','Horsepower','Voltage','Speed RPM','Invoice reference (if known)','Payment reference (if known)'];
  const options = (items, selected, label) => items.map(i => `<option value="${E(i.id)}" ${i.id === selected ? 'selected' : ''}>${E(label(i))}</option>`).join('');
  const button = (action, label, id = '') => `<button type="button" data-intake="${action}" data-id="${E(id)}">${E(label)}</button>`;
  function editor(a, prefix = '') {
    const manufacturers = [...new Set(U.state.report.assets.map(a => a.manufacturer).filter(Boolean))];
    const models = [...new Set(U.state.report.assets.filter(x => !a.manufacturer || x.manufacturer === a.manufacturer).map(a => a.model))];
    return `<div class="v2-grid">${fields.map((f, i) => input(prefix + f, labels[i], a[f], ['tag','model','site'].includes(f) ? 'required' : f === 'manufacturer' ? 'list="registry-makers"' : f === 'model' ? 'list="registry-models"' : '')).join('')}</div><datalist id="registry-makers">${manufacturers.map(m => `<option value="${E(m)}"></option>`).join('')}</datalist><datalist id="registry-models">${models.map(m => `<option value="${E(m)}"></option>`).join('')}</datalist>`;
  }
  function registry() {
    const r = U.state.report, a = r.assets.find(a => a.id === U.state.aid);
    return `<section class="work-sheet" id="registry-records"><h2>Editable machine registry</h2><p>${r.assets.length} machines · ${r.claims.length} claims · ${r.findings.filter(f => f.computed_status === 'supported').length} computed supported · ${r.claims.length-r.findings.filter(f => f.computed_status === 'supported').length} requiring evidence/review · ${r.evidence.length} evidence files · ${r.follow_ups.filter(f=>f.state==='open').length} open requests</p><label class="v2-field">Search machines<input id="registry-search" placeholder="Tag, manufacturer, model or serial"></label><div class="table-region"><div class="table-scroll"><table><thead><tr><th>Record</th><th>Manufacturer / model</th><th>Serial</th><th>Ratings</th><th>Source</th></tr></thead><tbody>${r.assets.map(x => `<tr data-registry-row="${E([x.tag,x.manufacturer,x.model,x.serial].join(' ').toLowerCase())}"><td>${button('edit-record',x.tag,x.id)}</td><td>${E(x.manufacturer || 'Unknown')}<br>${E(x.model)}</td><td>${E(x.serial || 'Unknown — review required')}</td><td>${E(x.rated_power_kw || '—')} kW · ${E(x.horse_power || '—')} HP<br>${E(x.rated_voltage_v || '—')} V · ${E(x.rated_speed_rpm || '—')} RPM</td><td>${E(x.provenance?.label_status || 'Analyst declaration')}</td></tr>`).join('')}</tbody></table></div></div>${a ? `<details class="subdisclosure" open><summary>Edit ${E(a.tag)}</summary><p>Saving resets the six declaration confirmations and makes earlier findings stale. Missing identifiers stay blank.</p><form data-intake-form="registry" data-target="${E(a.id)}" data-version="${a.version}">${editor(a)}<p class="small">Provenance: ${E(JSON.stringify(a.provenance))}</p>${input('reason','Reason for saved changes','','required maxlength="4000"')}<button type="submit" ${!U.analyst?'disabled':''}>Save record</button></form></details>` : ''}</section>`;
  }
  function inbox() {
    const r = U.state.report, current = S.items.find(i => i.id === S.selected);
    return `<section class="work-sheet" id="evidence-inbox"><h2>Evidence intake and review</h2><p>Photos, PDFs, text and MP4/MOV videos (12 MiB, 30 seconds, six frames). Originals are retained. Suggestions do not verify claims.</p>${U.analyst ? `<form data-intake-form="upload"><label class="v2-field">Original file<input type="file" name="file" accept=".pdf,.jpg,.jpeg,.png,.txt,.mp4,.mov" required></label>${input('source','Source / capture context','','required')}${input('captured_at','Captured at',new Date().toISOString().slice(0,16),'type="datetime-local" required')}${input('reason','Upload reason','Analyst evidence intake','required')}<button type="submit">Save original</button></form>` : ''}<label class="v2-field">Evidence inbox<select id="intake-picker"><option value="">Select an upload or frame</option>${options(S.items,S.selected,i => `${i.timestamp_seconds!=null?'Frame '+i.timestamp_seconds+'s · ':''}${i.suggested_title || r.evidence.find(e=>e.id===i.evidence_id)?.filename || i.id} · ${i.state}`)}</select></label>${current ? detail(current) : '<p>Unassigned uploads and processed frames appear here.</p>'}<p>For conversation recordings, transcripts and dedicated machine sound, use the existing Site inspection capture modes. <a href="/field-test">Open field capture bench</a>.</p></section>`;
  }
  function detail(i) {
    const ev = U.state.report.evidence.find(e => e.id === i.evidence_id);
    if (!ev) return '';
    const src = root() + `/evidence/${ev.id}/original`;
    const raw = i.raw_extraction, f = raw.fields || {};
    const candidate = i.candidates.find(c => c.method !== 'model_only');
    const target = U.state.report.assets.find(a => a.id === (i.selected_asset_id || candidate?.asset_id));
    const values = Object.fromEntries(fields.map(k => [k, f[k]?.length === 1 ? f[k][0] : '']));
    values.site ||= U.state.report.inspection.site;
    const preview = ev.media_type.startsWith('video/') ? `<video controls playsinline preload="metadata" src="${src}" class="v2-camera"></video>` : ev.media_type.startsWith('image/') ? `<img src="${src}" alt="Original evidence" style="max-width:100%;max-height:420px;object-fit:contain">` : `<a href="${src}" target="_blank" rel="noopener">View original document</a>`;
    const closed = ['assigned','rejected'].includes(i.state);
    return `<article class="work-sheet"><h3>${E(i.suggested_title || ev.filename)}</h3><p>${E(i.state)} · ${E(i.decision)} · ${E(i.category)}</p>${i.error?`<p class="banner error">${E(i.error)}</p>`:''}<p class="small">Original: ${E(ev.filename)} · SHA-256 ${E(ev.sha256)}${i.timestamp_seconds!=null?' · source timestamp '+E(i.timestamp_seconds)+'s':''}</p>${preview}<p><a href="${src}" target="_blank" rel="noopener">Open/download immutable original</a>${button('open-evidence','Accept fields / link claims in evidence review',ev.id)}</p>${i.parent_id?`<p>Derived from ${button('select','source '+i.parent_id,i.parent_id)} · ${E(JSON.stringify(i.transform))}</p>`:''}<div class="section-actions">${U.analyst && i.state==='uploaded'?button('process','Process saved original',i.id):''}</div><details open><summary>Original extraction and candidate sources</summary><pre class="intake-raw">${E(JSON.stringify(raw,null,2))}</pre></details><p>${i.candidates.map(c => E(c.tag+': '+c.method+'; matches '+c.matches.join(', ')+'; conflicts '+c.conflicts.join(', '))).join('<br>') || 'No registry match. Keep unassigned or propose a new record.'}</p>${U.analyst && ev.media_type.startsWith('image/')?`<details class="subdisclosure"><summary>Crop / adjust a derived image</summary><form data-intake-form="transform" data-id="${i.id}" data-version="${i.version}"><p>Pixel bounds: left, top, right, bottom. Leave all blank for the full image. The source stays unchanged.</p><div class="v2-grid">${['left','top','right','bottom'].map(x=>input(x,x,'','type="number" min="0"')).join('')}<label>Clockwise rotation<select name="rotate"><option>0</option><option>90</option><option>180</option><option>270</option></select></label><label><input type="checkbox" name="autocontrast">Improve contrast</label></div>${input('reason','Reason for adjustment','','required')}<button type="submit">Save adjusted image</button></form></details>`:''}${U.analyst&&!closed&&!ev.media_type.startsWith('video/')?`<form data-intake-form="review" data-id="${i.id}" data-version="${i.version}" class="work-sheet"><h3>Review a registry proposal</h3><label>Action<select name="action"><option value="assign">Assign as context to existing record</option><option value="create">Create new record from reviewed fields</option><option value="update">Update existing record with reviewed fields</option><option value="reject">Reject this proposal</option></select></label><label>Target record<select name="target_id"><option value="">Choose record</option>${options(U.state.report.assets,target?.id,a=>a.tag+' · '+(a.serial||'serial unknown'))}</select></label><p>Creating/updating uses the fields below. Review every value; technical labels and model matches do not establish identity.</p>${editor(target ? {...target,...Object.fromEntries(Object.entries(values).filter(([,v])=>v))} : values,'review_')}<label class="check-label"><input type="checkbox" name="checked_original">I checked these fields against the original</label><label class="check-label"><input type="checkbox" name="acknowledge_conflicts">I reviewed unresolved/conflicting identifiers; my reason explains the decision</label>${input('reason','Decision reason','','required maxlength="4000"')}<button type="submit">Save reviewed proposal</button></form>`:''}</article>`;
  }
  async function perform(task) {
    if(S.busy)return; S.busy=true; U.note('Saving / processing evidence…');
    document.body.classList.add('intake-busy');
    try {await task();U.state.dirty=false;await U.refresh();U.note('Saved. Review and reconcile claims through the existing evidence workflow.');}
    catch(e){U.note(e.message,true);}finally{S.busy=false;document.body.classList.remove('intake-busy');}
  }
  document.addEventListener('input',e=>{if(e.target.id==='registry-search')document.querySelectorAll('[data-registry-row]').forEach(row=>{row.hidden=!row.dataset.registryRow.includes(e.target.value.toLowerCase());});});
  document.addEventListener('change',e=>{
    if(e.target.id==='intake-picker'){if(S.busy)return;S.selected=e.target.value;U.render();}
    if(e.target.name==='manufacturer'||e.target.name==='review_manufacturer'){
      const list=document.querySelector('#registry-models');if(list)list.innerHTML=[...new Set(U.state.report.assets.filter(a=>a.manufacturer===e.target.value).map(a=>a.model))].map(m=>`<option value="${E(m)}"></option>`).join('');
    }
    if(e.target.name==='target_id'&&e.target.closest('[data-intake-form="review"]')){
      const a=U.state.report.assets.find(a=>a.id===e.target.value);if(a)for(const k of fields)e.target.form.elements['review_'+k].value=a[k]||'';
    }
  });
  document.addEventListener('click',e=>{const b=e.target.closest('[data-intake]');if(!b)return;e.preventDefault();if(S.busy)return;
    if(b.dataset.intake==='edit-record'){U.state.aid=b.dataset.id;U.render();document.querySelector('#registry-records details')?.scrollIntoView({block:'start'});}
    if(b.dataset.intake==='select'){S.selected=b.dataset.id;U.render();}
    if(b.dataset.intake==='process')perform(()=>U.api(root()+`/intake/${b.dataset.id}/process`,{method:'POST',body:{reason:'Analyst requested real extraction from saved original'}}));
    if(b.dataset.intake==='open-evidence'){U.state.eid=b.dataset.id;U.state.showAllFiles=true;U.state.evidenceStep=2;U.state.view='evidence';location.hash='/evidence';U.render();}
  });
  document.addEventListener('submit',e=>{const form=e.target;if(!form.dataset.intakeForm)return;e.preventDefault();if(!U.analyst||S.busy)return;const v=Object.fromEntries(new FormData(form));
    perform(async()=>{
      if(form.dataset.intakeForm==='upload'){
        const data=new FormData(form);data.set('captured_at',new Date(v.captured_at).toISOString());const item=await U.api(root()+'/intake',{method:'POST',body:data,key:form.dataset.key ||= crypto.randomUUID()});S.selected=item.id;
      }
      if(form.dataset.intakeForm==='registry'){
        const a=U.state.report.assets.find(a=>a.id===form.dataset.target);const body={...Object.fromEntries(fields.map(k=>[k,v[k]||null])),provenance:a.provenance,version:Number(form.dataset.version),reason:v.reason};await U.api(root()+`/assets/${a.id}`,{method:'PATCH',body});
      }
      if(form.dataset.intakeForm==='transform'){
        const bounds=['left','top','right','bottom'].map(k=>v[k]);if(bounds.some(Boolean)&&!bounds.every(x=>x!==''))throw Error('Enter all four crop bounds.');
        const item=await U.api(root()+`/intake/${form.dataset.id}/transform`,{method:'POST',body:{version:Number(form.dataset.version),crop:bounds.some(Boolean)?bounds.map(Number):null,rotate:Number(v.rotate),autocontrast:!!v.autocontrast,reason:v.reason}});S.selected=item.id;
      }
      if(form.dataset.intakeForm==='review'){
        const target=U.state.report.assets.find(a=>a.id===v.target_id);const body={version:Number(form.dataset.version),action:v.action,target_id:v.target_id||null,target_version:target?.version||null,checked_original:!!v.checked_original,acknowledge_conflicts:!!v.acknowledge_conflicts,reason:v.reason};
        if(['create','update'].includes(v.action))body.fields={...Object.fromEntries(fields.map(k=>[k,v['review_'+k]||null])),provenance:target?.provenance||{origin:'reviewed_scan_proposal',evidence_id:S.items.find(i=>i.id===form.dataset.id)?.evidence_id},reason:v.reason};
        await U.api(root()+`/intake/${form.dataset.id}/review`,{method:'POST',body});
      }
    });
  });
  window.CDIIntake={async load(){S.items=U.state.iid?await U.api(root()+'/intake'):[];if(S.selected&&!S.items.some(i=>i.id===S.selected))S.selected=null;},panel(view){return view==='overview'?registry():['evidence','site'].includes(view)?inbox():'';}};
})();
