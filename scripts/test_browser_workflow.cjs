/* End-to-end regression against an isolated SQLite app and synthetic evidence only.
 * Install the optional test dependency in an ignored test directory:
 * npm install --prefix .run/browser-tests --no-save playwright@1.62.1
 * Set NODE_PATH to .run/browser-tests/node_modules, install Chromium with its
 * playwright CLI, then run: node scripts/test_browser_workflow.cjs
 * Set CDI_BROWSER_TEST_PYTHON to the project venv's Python when needed.
 */
'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {randomBytes} = require('node:crypto');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium, expect} = require('playwright/test');

(async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'cdi-browser-'));
  const listener=net.createServer();
  await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
  const port=listener.address().port;
  await new Promise(resolve=>listener.close(resolve));
  const base=`http://127.0.0.1:${port}`,token=randomBytes(32).toString('hex');
  const server=spawn(process.env.CDI_BROWSER_TEST_PYTHON||'python',[
    '-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',String(port),'--no-access-log'
  ],{cwd:path.resolve(__dirname,'..'),env:{...process.env,DATABASE_URL:'',CDI_REQUIRE_POSTGRES:'false',
    CDI_TOKENS:JSON.stringify({[token]:{actor:'Browser regression analyst',role:'analyst'}}),CDI_DATA_DIR:directory},stdio:['ignore','pipe','pipe']});
  let logs='',launchError;
  server.stdout.on('data',b=>logs+=b);server.stderr.on('data',b=>logs+=b);server.on('error',e=>launchError=e);
  let browser;
  try{
    let ready=false;
    for(let i=0;i<100;i++){
      if(launchError)throw launchError;
      if(server.exitCode!==null)throw new Error(logs);
      try{ready=(await fetch(base+'/health')).ok;}catch{}
      if(ready)break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert.ok(ready,'Isolated app started');
    browser=await chromium.launch({headless:true,...(process.env.CDI_BROWSER_EXECUTABLE?{executablePath:process.env.CDI_BROWSER_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/login');
    await page.locator('input[name=token]').fill(token);
    await page.locator('button[type=submit]').click();
    await page.getByRole('button',{name:'Prepare fresh Plant A trial'}).click();
    await page.getByRole('heading',{name:'A clear view of Plant A'}).waitFor();
    const iid=await page.evaluate(()=>state.iid),root=base+'/api/v1/inspections/'+iid;
    const headers={Authorization:'Bearer '+token};
    const api=async(endpoint,method='GET',data)=>{
      const response=await page.request.fetch(root+endpoint,{method,headers,...(data?{data}:{})});
      assert.ok(response.ok(),await response.text());return response.json();
    };
    const idle=()=>page.waitForFunction(()=>!state.busy);
    const nextPage=view=>page.waitForFunction(view=>state.view===view&&!state.busy,view);
    const go=async(view)=>{await page.locator(`.nav-rail a[data-view=${view}]`).click();await nextPage(view);await expect(page.locator('.nav-rail [aria-current=page]')).toHaveAttribute('data-view',view);};
    const snapshot=await api('/export');
    const machine=tag=>snapshot.assets.find(a=>a.tag===tag);
    const selectMachine=async tag=>{await page.locator('.context-line select[name=asset_id]').selectOption(machine(tag).id);};
    const selectClaim=async kind=>{const cid=snapshot.claims.find(c=>c.asset_id===machine('CNC-002').id&&c.kind===kind).id;await page.locator('.context-line select[name=claim_id]').selectOption(cid);};
    const files=()=>page.locator('#evidence-picker option:not([value=""])').allTextContents();

    await go('evidence');
    assert.ok((await files()).every(name=>name.includes('CNC-002')));
    const originalCount=(await files()).length;assert.ok(originalCount>0);
    await page.getByRole('button',{name:'Show all files',exact:true}).click();
    assert.ok((await files()).length>originalCount);
    await page.getByRole('button',{name:'Show CNC-002 files only'}).click();
    await page.locator('#evidence-picker').selectOption({index:1});
    await selectMachine('CNC-003');
    assert.equal(await page.locator('#evidence-picker').inputValue(),'');
    assert.ok((await files()).every(name=>name.includes('CNC-003')));
    await selectMachine('CNC-002');
    await selectClaim('commissioning');

    // Upload an unassigned filename: the selected machine must retain the new original.
    const pdf=await page.request.get(root+'/demo-certificate/'+machine('CNC-002').id,{headers});
    await page.locator('#evidence-file').setInputFiles({name:'certificate.pdf',mimeType:'application/pdf',buffer:await pdf.body()});
    await page.locator('#upload-evidence input[name=source]').fill('Synthetic browser regression');
    await page.locator('#upload-evidence input[name=reason]').fill('Import certificate for CNC-002');
    await page.locator('#upload-evidence button[type=submit]').click();await idle();
    await expect(page.locator('.step[open]')).toHaveAttribute('data-step','2');
    assert.ok((await files()).some(name=>name.includes('certificate.pdf')));
    await page.getByRole('button',{name:'Extract text / OCR',exact:true}).click();await idle();
    await expect(page.locator('input[name=fact_serial]')).toHaveValue('SYN-002');
    await page.locator('#correct-evidence input[name=reason]').fill('Checked original synthetic certificate');
    await page.getByRole('button',{name:'Save and confirm'}).click();await idle();
    await expect(page.locator('#message')).toContainText('check the confirmation box');
    await expect(page.locator('.step[open]')).toHaveAttribute('data-step','2');
    await page.locator('input[name=checked_original]').check();
    await page.getByRole('button',{name:'Save and confirm'}).click();await idle();
    await expect(page.locator('.step[open]')).toHaveAttribute('data-step','3');
    await page.locator('#link-evidence input[name=locator]').fill('Page 1');
    await page.locator('#link-evidence input[name=reason]').fill('Certificate addresses this commissioning claim');
    await page.locator('#link-evidence button[type=submit]').click();await nextPage('site');

    await page.getByRole('button',{name:'Use this machine'}).click();
    await expect(page.locator('.step[open]')).toHaveAttribute('data-step','2');
    await page.locator('#observe textarea[name=text]').fill('Operating at site; installation explicitly observed.');
    await page.locator('#observe input[name=reason]').fill('Analyst verified the physical equipment');
    await page.locator('#observe button[type=submit]').click();await idle();
    await expect(page.locator('.step[open]')).toHaveAttribute('data-step','3');
    await page.locator('#link-observation input[name=reason]').fill('Observation covers presence and installation');
    await page.locator('#link-observation button[type=submit]').click();await nextPage('assessment');
    assert.ok((await api('/export')).reconciliation_current);
    await selectClaim('commissioning');
    await page.locator('#review-finding textarea[name=reason]').fill('Agree with accepted and matched certificate');
    await page.locator('#review-finding button[type=submit]').click();await idle();
    assert.notEqual(await page.evaluate(()=>state.cid),snapshot.claims.find(c=>c.asset_id===machine('CNC-002').id&&c.kind==='commissioning').id);
    await page.getByRole('button',{name:/Review \d+ unchanged findings/}).click();
    await page.locator('#batch-review input[name=checked]').check();
    await page.locator('#batch-review input[name=reason]').fill('Read all unchanged conclusions against current evidence');
    await page.locator('#batch-review button[type=submit]').click();await idle();
    await expect(page.locator('#complete-review')).toBeVisible();
    await page.locator('#complete-review input[name=reason]').fill('All findings reviewed; remaining gaps stay open');
    await page.locator('#complete-review button[type=submit]').click();await nextPage('overview');
    await expect(page.locator('.summary-line')).toContainText('16 supported');
    await expect(page.locator('.summary-line')).toContainText('Review complete');

    // A rejected save must retain the form, current page and entries.
    await go('assessment');
    await selectMachine('CNC-003');
    const installation=snapshot.claims.find(c=>c.asset_id===machine('CNC-003').id&&c.kind==='installation');
    await page.locator('.context-line select[name=claim_id]').selectOption(installation.id);
    await page.locator('#review-status').selectOption('supported');
    await page.locator('#review-finding textarea[name=reason]').fill('Deliberate reviewer override for regression only');
    await page.route('**/findings/*/review',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Synthetic version conflict'})}));
    await page.locator('#review-finding button[type=submit]').click();await idle();
    await expect(page.locator('#message')).toContainText('Synthetic version conflict');
    await expect(page.locator('#review-finding textarea')).toHaveValue('Deliberate reviewer override for regression only');
    assert.equal(await page.evaluate(()=>state.view),'assessment');
    await page.unroute('**/findings/*/review');
    await page.locator('#review-finding button[type=submit]').click();await idle();
    await page.locator('#complete-review input[name=reason]').fill('Override reviewed; computed conclusion retained');
    await page.locator('#complete-review button[type=submit]').click();await nextPage('overview');
    await expect(page.locator('.summary-line')).toContainText('17 supported');
    const cell=page.locator(`#matrix-scroll [data-cid="${installation.id}"]`);
    await expect(cell.locator('.status')).toHaveText('Supported');
    await expect(cell).toContainText('Computed: Unresolved');
    await expect(page.locator('#workspace')).toContainText('Computed support: 16 of 18');

    // Another client changes the review: navigation must refetch, not render cached JSON.
    await go('assessment');
    let report=await api('/export'),f=report.findings.find(f=>f.claim_id===installation.id);
    await api('/findings/'+f.id+'/review','PATCH',{version:f.version,status:'unresolved',reason:'External client restores reviewed conclusion'});
    await api('/review-complete','POST',{reason:'External review completed'});
    await go('overview');
    await expect(page.locator('.summary-line')).toContainText('16 supported');
    await expect(cell.locator('.status')).toHaveText('Unresolved');

    await page.locator('#tab-activity').click();
    const normalHeight=(await page.locator('#tray-panel').boundingBox()).height;
    await page.locator('#tray-expand').click();
    assert.ok((await page.locator('#tray-panel').boundingBox()).height>normalHeight);
    await expect(page.locator('#tray-expand')).toHaveAttribute('aria-expanded','true');
    await page.locator('#tab-requests').click();
    await expect(page.locator('#tray-expand')).toHaveAttribute('aria-expanded','true');
    await page.setViewportSize({width:390,height:844});
    const tray=await page.locator('.bottom-tray').boundingBox();
    assert.ok(tray.x>=0&&tray.x+tray.width<=391&&tray.y>=0);
    await expect(page.locator('#tray-expand')).toBeInViewport();
    await expect(page.locator('#tray-close')).toBeInViewport();
    await page.locator('#tray-expand').click();
    await expect(page.locator('#tray-expand')).toHaveAttribute('aria-expanded','false');
    await page.keyboard.press('Escape');
    await expect(page.locator('#tray-panel')).toBeHidden();

    // Unassigned originals remain discoverable; a stale assessment cannot show old support.
    await page.request.post(root+'/evidence',{headers,multipart:{kind:'invoice',source:'Regression test',
      captured_at:'2026-01-01T00:00:00Z',reason:'Unassigned document makes reconciliation stale',
      file:{name:'unassigned.txt',mimeType:'text/plain',buffer:Buffer.from('Unassigned synthetic evidence')}}});
    await go('evidence');
    assert.ok(!(await files()).some(name=>name.includes('unassigned.txt')));
    await page.getByRole('button',{name:'Show all files',exact:true}).click();
    assert.ok((await files()).some(name=>name.includes('unassigned.txt')));
    await go('overview');
    await expect(page.locator('.summary-line')).toContainText('Findings need reconciliation');
    assert.equal(await page.locator('#matrix-scroll .status.supported').count(),0);
    assert.deepEqual(errors,[]);
    console.log('Browser workflow passed: fresh overview, guarded saves, automatic progression, machine filter, overrides, external refresh, stale findings, expandable desktop/mobile tray.');
  }catch(error){console.error(logs);throw error;}
  finally{
    if(browser)await browser.close();
    if(server.pid&&server.exitCode===null&&server.signalCode===null){
      const exited=new Promise(resolve=>server.once('exit',resolve));
      if(process.platform==='win32'){
        // Windows venv Python has a launcher and a separate interpreter process.
        // This PID comes only from this runner's own Uvicorn startup log.
        const interpreter=Number(logs.match(/Started server process \[(\d+)\]/)?.[1]);
        if(interpreter&&interpreter!==server.pid){try{process.kill(interpreter);}catch(error){if(error.code!=='ESRCH')throw error;}}
        server.kill();
      }else server.kill();
      await Promise.race([exited,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Test server did not stop')),5000))]);
    }
    const resolved=path.resolve(directory),tempRoot=path.resolve(os.tmpdir())+path.sep;
    assert.ok(resolved.startsWith(tempRoot)&&path.basename(resolved).startsWith('cdi-browser-'),'Cleanup stays inside the temporary test directory');
    await fs.rm(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:200});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
