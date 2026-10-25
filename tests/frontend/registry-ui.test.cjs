const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require(process.env.CDI_JSDOM_PATH||'jsdom');
const fs=require('node:fs');
function fixture({judge=false,fail=false}={}){
 const dom=new JSDOM('<div id="workspace"></div>',{url:'http://localhost/app',runScripts:'outside-only'}),w=dom.window,calls=[];
 const a={id:'a1',version:3,tag:'MTR-001',manufacturer:'Maker',model:'M1',serial:null,site:'Demo site',rated_power_kw:'15 kW',rated_voltage_v:'400 V',rated_speed_rpm:'1500 RPM',provenance:{label_status:'publisher_auto_generated_unverified'}};
 w.IntegrityUI={analyst:!judge,state:{iid:'i',aid:a.id,report:{assets:[a],claims:[],findings:[],follow_ups:[],evidence:[]}},api:async(...args)=>{calls.push(args);if(fail)throw Error('Stale version');return a;},note:()=>{},refresh:async()=>{},render:()=>{w.document.querySelector('#workspace').innerHTML=w.CDIIntake.panel('registry');}};
 w.eval(fs.readFileSync('app/static/registry.js','utf8'));w.IntegrityUI.render();return {w,calls};
}
test('registry preserves nulls and prevents doubled rating units',()=>{
 const {w}=fixture();const text=w.document.querySelector('#workspace').textContent;
 assert.ok(text.includes('Unknown — review required'));assert.ok(!text.includes('15 kW kW'));assert.ok(!text.includes('400 V V'));assert.equal(w.document.querySelector('[name=serial]').value,'');
});
test('saved registry edit carries original version and provenance; stale save retains entries',async()=>{
 const {w,calls}=fixture({fail:true}),form=w.document.querySelector('form');form.elements.manufacturer.value='Reviewed Maker';form.elements.reason.value='Checked original';form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10));
 assert.equal(calls[0][1].body.version,3);assert.equal(calls[0][1].body.serial,null);assert.equal(calls[0][1].body.provenance.label_status,'publisher_auto_generated_unverified');assert.equal(form.elements.manufacturer.value,'Reviewed Maker');
});
test('judge cannot dispatch a forged registry submission',async()=>{
 const {w,calls}=fixture({judge:true});w.document.querySelector('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10));assert.equal(calls.length,0);
});
