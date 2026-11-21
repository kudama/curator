'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function setup(){const c=vm.createContext({URLSearchParams});vm.runInContext(source,c);return code=>vm.runInContext(code,c);}
test('history includes failures and excludes waiting/active/recommendations',()=>{
 const run=setup();for(const status of ['applied','resolved','rejected','cancelled','blocked','failed'])assert.equal(run(`historyStatusMatches({status:'${status}'})`),true);
 for(const status of ['recommendation','queued','running','publishing','awaiting_review'])assert.equal(run(`historyStatusMatches({status:'${status}'})`),false);
});
test('each filter is exact and Completed includes applied and resolved',()=>{
 const run=setup();run("historyStatus='completed'");assert.equal(run("historyStatusMatches({status:'applied'})"),true);assert.equal(run("historyStatusMatches({status:'resolved'})"),true);assert.equal(run("historyStatusMatches({status:'cancelled'})"),false);
 for(const status of ['cancelled','rejected','failed','blocked']){run(`historyStatus='${status}'`);assert.equal(run(`historyStatusMatches({status:'${status}'})`),true);assert.equal(run("historyStatusMatches({status:'applied'})"),false);}
});
test('library scope and period filters',()=>{
 const run=setup();run("libraryId='one'");
 assert.equal(run("historyLibraryMatches('one')"),true);assert.equal(run("historyLibraryMatches('two')"),false);
 run("historyScope='all'");assert.equal(run("historyLibraryMatches('two')"),true);
 const now=Date.parse('2026-11-20T12:00:00Z');
 assert.equal(run(`historyInPeriod('2020-01-01T00:00:00Z',${now})`),true);
 run("historyPeriod='7'");
 assert.equal(run(`historyInPeriod('2026-11-14T12:00:00Z',${now})`),true);
 assert.equal(run(`historyInPeriod('2026-11-12T12:00:00Z',${now})`),false);
 assert.equal(run(`historyInPeriod(undefined,${now})`),false);
 assert.equal(run(`historySince(${now})`),'2026-11-13T12:00:00.000Z');
});
test('curator history query follows the filters',()=>{
 const run=setup();run("libraryId='one';historyView='curator'");
 assert.equal(run("curatorHistoryQuery().toString()"),'view=curator&limit=100&library=one');
 run("historyScope='all';historyLevel='error'");
 assert.equal(run("curatorHistoryQuery(42).toString()"),'view=curator&limit=100&level=error&before=42');
});
test('controls show the status filter for jobs and the level filter for Curator events',()=>{
 const run=setup(),elements={};
 for(const id of ['history-view','history-scope','history-period','history-level','history-status'])for(const suffix of ['','-control'])elements[id+suffix]={hidden:false,value:''};
 run('screen="history"');const c=run('this');c.$=id=>elements[id];
 run('renderHistoryControls()');
 assert.equal(elements['history-status-control'].hidden,false);assert.equal(elements['history-level-control'].hidden,true);assert.equal(elements['history-view'].value,'jobs');
 run("historyView='curator'");run('renderHistoryControls()');
 assert.equal(elements['history-status-control'].hidden,true);assert.equal(elements['history-level-control'].hidden,false);
 run("screen='library'");run('renderHistoryControls()');
 assert.ok(Object.entries(elements).filter(([k])=>k.endsWith('-control')).every(([,e])=>e.hidden));
});
test('older pages append and a response for old filters is dropped',async()=>{
 const run=setup(),c=run('this');let renders=0;const calls=[];c.render=()=>{renders++;};
 c.api=async path=>{calls.push(path);return calls.length===1?{events:[{id:9}],next:9}:{events:[{id:3}],next:null};};
 run("libraryId='one';historyScope='all'");
 await run('loadCuratorHistory()');await run('loadCuratorHistory(true)');
 assert.equal(run('curatorHistory.events.map(e=>e.id).join()'),'9,3');assert.match(calls[1],/before=9/);assert.equal(renders,2);
 let release;c.api=()=>new Promise(resolve=>{release=resolve;});
 const stale=run('loadCuratorHistory()');run("historyLevel='error'");c.api=async()=>({events:[{id:1}],next:null});
 await run('loadCuratorHistory()');release({events:[{id:99}],next:null});await stale;
 assert.equal(run('curatorHistory.events.map(e=>e.id).join()'),'1');
});
function recoveryHarness(task,{available=true}={}){
 const run=setup(),c=run('this'),calls=[],pane={scrollTop:240};
 c.taskAvailable=()=>available;c.state={tasks:[{...task}]};c.toast=message=>calls.push({toast:message});
 c.document={querySelector:()=>pane};c.refresh=async()=>{calls.push('refresh');};
 c.api=async(path,data)=>{calls.push({path,data});return path==='recovery/retry-failed'?{items:[{id:task.id,status:'queued'}]}:{};};
 return {run,c,calls,pane};
}
const base={id:'t1',asset:'a1',library:'one',version:3};
test('each finished, failed, blocked, interrupted and cancelled state maps to an existing action or a reason',()=>{
 const call=(task,opts)=>{const h=recoveryHarness({...base,...task},opts);h.c.subject=h.c.state.tasks[0];return JSON.parse(h.run('JSON.stringify(historyRecovery(subject))'));};
 assert.equal(call({kind:'upscale',status:'applied'}),null);
 assert.equal(call({kind:'upscale',status:'blocked',output:'/o',source_hash:'s',output_hash:'o'}).action.call,'resume_review');
 assert.match(call({kind:'upscale',status:'blocked',output:'/o',source_hash:'s',output_hash:'o',published:true}).text,/Publication may be incomplete/);
 assert.equal(call({kind:'upscale',status:'blocked',output:'/o',source_hash:'s',output_hash:'o',published:true}).action,undefined);
 assert.match(call({kind:'upscale',status:'blocked',output:'/o',validation:['bad frames']}).text,/did not pass validation/);
 assert.equal(call({kind:'metadata',status:'failed',plan:{changes:{summary:'x'}}}).action.call,'retry');
 assert.equal(call({kind:'optimize',status:'blocked',error:'Interrupted operation'}).action.call,'retry');
 const cancelled=call({kind:'optimize',status:'cancelled'});assert.equal(cancelled.action,undefined);assert.match(cancelled.text,/View the job/);
 assert.match(call({kind:'metadata',status:'failed'},{available:false}).text,/missing from the catalog/);
 assert.match(call({kind:'rename',status:'blocked',rename_started:true}).text,/restore the original filenames/);
 assert.match(call({kind:'join',status:'blocked',output:'/j'}).text,/joined output/);
 assert.match(call({kind:'mage_generation',status:'failed'}).text,/artwork review/);
 assert.match(call({kind:'tag',status:'rejected'}).text,/stay closed/);
 assert.match(call({kind:'upscale',status:'applied',cleanup_pending:true}).text,/Cleanup/);
 for(const status of ['applied','resolved','rejected','cancelled','failed','blocked'])for(const kind of ['upscale','metadata','rename','join','artwork','folder_metadata','inspect']){
  const result=call({kind,status,output:status==='blocked'?'/o':undefined});if(result&&result.action)assert.ok(['retry','resume_review'].includes(result.action.call));
 }
});
test('a stale snapshot is rejected after re-reading current state, without any request',async()=>{
 const h=recoveryHarness({...base,kind:'metadata',status:'failed'});const snapshot={...h.c.state.tasks[0]};
 h.c.refresh=async()=>{h.calls.push('refresh');h.c.state={tasks:[{...snapshot,version:4}]};};
 h.c.snapshot=snapshot;
 await assert.rejects(h.run("historyRecoveryAction(snapshot,{call:'retry'})"),/changed since History was shown/);
 assert.equal(h.calls.filter(x=>typeof x==='object').length,0);
});
test('retry re-reads, sends the current version, never starts the queue and keeps the scroll position',async()=>{
 const h=recoveryHarness({...base,kind:'metadata',status:'failed'});h.c.snapshot={...h.c.state.tasks[0]};
 h.c.refresh=async()=>{h.calls.push('refresh');h.pane.scrollTop=0;};
 await h.run("historyRecoveryAction(snapshot,{call:'retry'})");
 const requests=h.calls.filter(x=>x.path);assert.equal(requests.length,1);assert.equal(requests[0].path,'recovery/retry-failed');
 assert.equal(JSON.stringify(requests[0].data),JSON.stringify({tasks:[{id:'t1',version:3}]}));
 assert.ok(!h.calls.some(x=>x.path==='run'));assert.equal(h.calls.filter(x=>x==='refresh').length,2);assert.equal(h.pane.scrollTop,240);
 assert.match(h.calls.find(x=>x.toast).toast,/has not been started/);
});
test('a refused recovery (missing output) is reported and the list still refreshes',async()=>{
 const h=recoveryHarness({...base,kind:'upscale',status:'blocked',output:'/o',source_hash:'s',output_hash:'o'});h.c.snapshot={...h.c.state.tasks[0]};
 h.c.api=async()=>{throw Error('No validated, unpublished output is available to review');};
 await assert.rejects(h.run("historyRecoveryAction(snapshot,{call:'resume_review'})"),/No validated/);
 assert.equal(h.calls.filter(x=>x==='refresh').length,2);
});
test('a retry the server refuses is reported, not shown as queued',async()=>{
 const h=recoveryHarness({...base,kind:'metadata',status:'failed'});h.c.snapshot={...h.c.state.tasks[0]};
 h.c.api=async()=>({items:[{id:'t1',status:'failed',error:'Task changed, source/settings unavailable, or manual recovery required'}]});
 await assert.rejects(h.run("historyRecoveryAction(snapshot,{call:'retry'})"),/manual recovery required/);
 assert.ok(!h.calls.some(x=>x.toast));
});
