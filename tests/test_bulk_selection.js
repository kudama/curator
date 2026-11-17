'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function setup(){const tasks=Array.from({length:1368},(_,i)=>({id:String(i),asset:'a'+i,library:'one',kind:'upscale',status:'awaiting_review',version:1}));const byAsset=new Map(tasks.map(t=>[t.asset,[t]]));const context=vm.createContext({state:{tasks},selected:new Set(),libraryId:'one',inspectorDirty:true,taskAvailable:()=>true,catalogIndex:()=>({byAsset}),api(){throw Error('Selection must not mutate the server');}});vm.runInContext(source,context);return {tasks,context,run:code=>vm.runInContext(code,context)};}
test('selects all1368 tasks without API calls and can clear them',()=>{const w=setup();w.run('selectTaskRows(state.tasks,true)');assert.equal(w.context.selected.size,1368);assert.equal(w.context.inspectorDirty,true);w.run('selectTaskRows(state.tasks,false)');assert.equal(w.context.selected.size,0);});
test('task-group selection is scoped to the filtered files and task kind',()=>{const w=setup();w.context.group={id:'upscale',files:w.tasks.slice(0,40).map(t=>({id:t.asset}))};w.run('selectTaskRows(groupTaskRows(group),true)');assert.equal(w.context.selected.size,40);assert.equal(w.context.selected.has('40'),false);});
test('refresh removes changed versions, finished tasks and disappeared tasks',()=>{const w=setup();w.run('selectTaskRows(state.tasks,true)');w.tasks[0].version=2;w.tasks[1].status='applied';w.context.state.tasks=w.tasks.slice(0,-1);w.run('pruneGroupSelection()');assert.equal(w.context.selected.size,1365);assert.equal(w.context.selected.has('0'),false);assert.equal(w.context.selected.has('1'),false);assert.equal(w.context.selected.has('1367'),false);});
test('batch review excludes recommendations and unsupported task types',()=>{const w=setup();w.tasks[0].status='recommendation';w.tasks[1].kind='artwork';w.run('selectTaskRows(state.tasks,true)');assert.equal(w.run('reviewableRows(state.tasks).length'),1366);});
test('group queue action keeps failures selected and never starts the queue',async()=>{
 const w=setup(),calls=[];w.tasks.splice(3);for(const t of w.tasks)t.status='recommendation';
 w.context.canQueue=t=>t.status==='recommendation';w.context.refresh=async()=>{};w.context.toast=()=>{};w.context.render=()=>{};w.context.document={querySelectorAll:()=>[],getElementById:()=>({append(){}})};w.context.button=()=>({});
 w.context.api=async(path,data)=>{calls.push({path,data});if(data.id==='1')throw Error('Rejected');};
 w.run('selectTaskRows(state.tasks,true)');await w.run('queueTaskRows(state.tasks)');
 assert.deepEqual(calls.map(c=>c.path),['task/action','task/action','task/action']);
 assert.equal(calls[0].data.version,1);assert.equal(calls[0].data.action,'queue');
 assert.equal(w.context.selected.size,1);assert.equal(w.context.selected.has('1'),true);
});
test('cleanup cards stay visible in queue and completed receipts move to history',()=>{
 const w=setup();w.context.state.cleanup_jobs=[{id:'active',library:'one',phase:'deleting',total:9,completed:2,deleted:2,failed:0,current:{title:'Movie',phase:'Verifying'}},{id:'done',library:'one',phase:'complete',total:9,completed:9,deleted:0,failed:9}];
 w.context.node=(tag,text)=>({tag,text,children:[],append(...items){this.children.push(...items);}});w.context.button=(label)=>({label});
 const active=w.run('cleanupJobCards(false)'),done=w.run('cleanupJobCards(true)');
 assert.equal(active.length,1);assert.equal(done.length,1);
 assert.match(JSON.stringify(active),/Verifying/);assert.match(JSON.stringify(done),/Finished with failures/);
});
test('queueing reports progress immediately and duplicate clicks do not submit again',async()=>{
 const w=setup();w.tasks.splice(2);for(const t of w.tasks)t.status='recommendation';
 let release,calls=0;const pending=new Promise(resolve=>{release=resolve;});const labels=[];
 w.context.canQueue=()=>true;w.context.render=()=>{};w.context.refresh=async()=>{};w.context.toast=()=>{};w.context.button=()=>({});
 w.context.document={querySelectorAll:()=>[{set textContent(value){labels.push(value);}}],getElementById:()=>({append(){}})};
 w.context.api=async()=>{calls++;if(calls===1)await pending;};
 w.run('selectTaskRows(state.tasks,true)');const first=w.run('queueTaskRows(state.tasks)');
 assert.equal(w.run('queueProgressText()'),'Queueing 0 of 2…');
 await w.run('queueTaskRows(state.tasks)');assert.equal(calls,1);
 release();await first;assert.equal(calls,2);assert.deepEqual(labels,['Queueing 1 of 2…','Queueing 2 of 2…']);
});
