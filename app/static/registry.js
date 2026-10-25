/* Intake adds reviewed proposals to the existing evidence and registry workflow. */
(() => {
  'use strict';
  const U = window.IntegrityUI;
  const E = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const S = {busy: false, search: ""};
  const root = () => `/api/v1/inspections/${U.state.iid}`;
  const input = (name, label, value = '', extra = '') => `<label class="v2-field">${E(label)}<input name="${name}" value="${E(value)}" maxlength="200" ${extra}></label>`;
  const fields = ['tag','manufacturer','model','serial','site','rated_power_kw','horse_power','rated_voltage_v','rated_speed_rpm','invoice_ref','payment_ref'];
  const rating = (value, unit) => value ? E(value) + (new RegExp(unit + "$", "i").test(value.trim()) ? "" : " " + unit) : "— " + unit;
  const labels = ['Internal tag','Manufacturer','Model','Serial (blank if unknown)','Site association','Power kW','Horsepower','Voltage','Speed RPM','Invoice reference (if known)','Payment reference (if known)'];
  const button = (action, label, id = '') => `<button type="button" data-intake="${action}" data-id="${E(id)}">${E(label)}</button>`;
  function editor(a, prefix = '') {
    const manufacturers = [...new Set(U.state.report.assets.map(a => a.manufacturer).filter(Boolean))];
    const models = [...new Set(U.state.report.assets.filter(x => !a.manufacturer || x.manufacturer === a.manufacturer).map(a => a.model))];
    return `<div class="v2-grid">${fields.map((f, i) => input(prefix + f, labels[i], a[f], f === 'model' ? 'required list="registry-models"' : ['tag','site'].includes(f) ? 'required' : f === 'manufacturer' ? 'list="registry-makers"' : '')).join('')}</div><datalist id="registry-makers">${manufacturers.map(m => `<option value="${E(m)}"></option>`).join('')}</datalist><datalist id="registry-models">${models.map(m => `<option value="${E(m)}"></option>`).join('')}</datalist>`;
  }
  function registry() {
    const r = U.state.report, a = r.assets.find(a => a.id === U.state.aid);
    return `<section class="work-sheet" id="registry-records"><h2>Editable machine registry</h2><p>${r.assets.length} machines · ${r.claims.length} claims · ${r.findings.filter(f => f.computed_status === 'supported').length} computed supported · ${r.claims.length-r.findings.filter(f => f.computed_status === 'supported').length} requiring evidence/review · ${r.evidence.length} evidence files · ${r.follow_ups.filter(f=>f.state==='open').length} open requests</p><label class="v2-field">Search machines<input id="registry-search" value="${E(S.search)}" placeholder="Tag, manufacturer, model or serial"></label><div class="table-region"><div class="table-scroll"><table><thead><tr><th>Record</th><th>Manufacturer / model</th><th>Serial</th><th>Ratings</th><th>Source</th></tr></thead><tbody>${r.assets.map(x => `<tr data-registry-row="${E([x.tag,x.manufacturer,x.model,x.serial].join(' ').toLowerCase())}"><td>${button('edit-record',x.tag,x.id)}</td><td>${E(x.manufacturer || 'Unknown')}<br>${E(x.model)}</td><td>${E(x.serial || 'Unknown — review required')}</td><td>${rating(x.rated_power_kw,"kW")} · ${rating(x.horse_power,"HP")}<br>${rating(x.rated_voltage_v,"V")} · ${rating(x.rated_speed_rpm,"RPM")}</td><td>${E(x.provenance?.label_status || (x.provenance?.synthetic_demo ? "Synthetic demo" : "Analyst declaration"))}</td></tr>`).join('')}</tbody></table></div></div>${a ? `<details class="subdisclosure" open><summary>Edit ${E(a.tag)}</summary><p>Saving resets the six declaration confirmations and makes earlier findings stale. Missing identifiers stay blank.</p><form data-intake-form="registry" data-target="${E(a.id)}" data-version="${a.version}">${editor(a)}<p class="small">Provenance: ${E(JSON.stringify(a.provenance))}</p>${input('reason','Reason for saved changes','','required maxlength="4000"')}<button type="submit" ${!U.analyst?'disabled':''}>Save record</button></form></details>` : ''}</section>`;
  }
  async function perform(task) {
    if(S.busy)return; S.busy=true; U.note('Saving / processing evidence…');
    document.body.classList.add('intake-busy');
    try {await task();U.state.dirty=false;await U.refresh();U.note('Saved. Review and reconcile claims through the existing evidence workflow.');}
    catch(e){U.note(e.message,true);}finally{S.busy=false;document.body.classList.remove('intake-busy');}
  }
  document.addEventListener('input',e=>{if(e.target.id==='registry-search'){S.search=e.target.value;document.querySelectorAll('[data-registry-row]').forEach(row=>{row.hidden=!row.dataset.registryRow.includes(e.target.value.toLowerCase());});}});
  document.addEventListener('change',e=>{
    if(e.target.name==='manufacturer'||e.target.name==='review_manufacturer'){
      const list=document.querySelector('#registry-models');if(list)list.innerHTML=[...new Set(U.state.report.assets.filter(a=>a.manufacturer===e.target.value).map(a=>a.model))].map(m=>`<option value="${E(m)}"></option>`).join('');
    }
  });
  document.addEventListener('click',e=>{const b=e.target.closest('[data-intake]');if(!b)return;e.preventDefault();if(S.busy)return;
    if(b.dataset.intake==='edit-record'){U.state.aid=b.dataset.id;U.render();document.querySelectorAll("[data-registry-row]").forEach(row=>row.hidden=!row.dataset.registryRow.includes(S.search.toLowerCase()));document.querySelector('#registry-records details')?.scrollIntoView({block:'start'});}
  });
  document.addEventListener('submit',e=>{const form=e.target;if(!form.dataset.intakeForm)return;e.preventDefault();if(!U.analyst||S.busy)return;const v=Object.fromEntries(new FormData(form));
    perform(async()=>{
      if(form.dataset.intakeForm==='registry'){
        const a=U.state.report.assets.find(a=>a.id===form.dataset.target);const body={...Object.fromEntries(fields.map(k=>[k,v[k]||null])),provenance:a.provenance,version:Number(form.dataset.version),reason:v.reason};await U.api(root()+`/assets/${a.id}`,{method:'PATCH',body});
      }
    });
  });
  window.CDIIntake={async load(){},panel(view){return view==='overview'?registry():['evidence','site'].includes(view)?'<section class="work-sheet"><h2>Evidence intake</h2><p>Upload, process, review scan proposals and adjust source frames in the connected inbox.</p><a href="/evidence-inbox">Open Evidence Inbox →</a></section>':'';}};
})();
