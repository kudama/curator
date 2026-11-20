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
