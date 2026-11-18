'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.dataset={};this.attrs={};this.style={};}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k];}
 setPointerCapture(){}
 get classList(){return {add:cls=>{this.className+=' '+cls;},toggle:(cls,on)=>{if(on)this.className+=' '+cls;}};}
}
function setup(){
 const elements=new Map(),calls=[],cards=[];let target=null;
 const state={libraries:[{id:'one',title:'One'},{id:'two',title:'Two'}],tasks:[],assets:[],file_jobs:[],file_queue:[],global_queue:[],task_queues:[],queue_limits:{optimize:2}};
 const context=vm.createContext({state,screen:'processing',libraryId:'one',searchText:'',queueStatus:'all',openedTask:null,
  $:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},node:(...args)=>new Element(...args),
  button:(text,fn,cls)=>{const e=new Element('button',text,cls);e.onclick=fn;return e;},catalogIndex:()=>({byId:new Map()}),TASK_LABELS:{upscale:'Upscaling',optimize:'Encoding'},
  featureAvailable:()=>true,render(){},refresh:async()=>{},toast(){},api:async(endpoint,data)=>calls.push({endpoint,data}),run:fn=>fn(),
  document:{elementFromPoint:()=>({closest:()=>({dataset:{waitingId:target}})})}});
 for(const file of ['workbench','queue-board'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/'+file+'.js'),'utf8'),context);
 context.taskQueueControls=()=>new Element('div');context.bulkTaskControls=()=>new Element('div');context.cleanupJobCards=()=>state.cleanup_jobs?.filter(j=>j.phase!=='complete').map(j=>{const e=new Element('article');e.dataset.cleanupId=j.id;return e;})||[];
 context.processingTaskCard=t=>{cards.push(t.id);return new Element('article');};context.renderLegacyProcessing=()=>['legacy'];
 const add=(id,kind,status='queued',library='one')=>{const t={id,title:id,kind,status,library,version:1};state.tasks.push(t);if(status==='queued')state.global_queue.push({id,version:1});return t;};
 return {context,state,calls,cards,elements,add,target:id=>{target=id;},run:code=>vm.runInContext(code,context)};
}
function all(node){return [node,...node.children.flatMap(all)];}
test('three lanes keep all concurrent jobs and render the waiting head once',()=>{
 const h=setup();h.add('up','upscale','running');h.add('enc1','optimize','running');h.add('enc2','optimize','running');h.add('later','optimize');
 const board=h.run('renderProcessing()')[0];assert.equal(board.children.length,3);assert.deepEqual(new Set(h.cards),new Set(['up','enc1','enc2','later']));
 assert.equal(all(board).filter(e=>e.className.includes('queue-head')).length,2);
 const waiting=setup();waiting.add('first','upscale');waiting.run('renderProcessing()');assert.deepEqual(waiting.cards,['first']);
});
test('publication is counted once and other tasks do not replace the board',()=>{
 const h=setup();h.add('publication','optimize','publishing');h.state.file_jobs=[{id:'file',phase:'running',operation:'publish',title:'Publication',library:'one',payload:{task:'publication'}}];
 assert.equal(h.run('queueCountRows().length'),1);h.run('renderProcessing()');assert.equal(h.cards.includes('publication'),false);
 h.add('metadata','metadata');assert.equal(h.run('queueBoardAvailable()'),true);const sections=h.run('renderProcessing()');assert.equal(sections[0].children.length,3);assert.equal(sections.length,2);assert.ok(h.cards.includes('metadata'));
});
test('filtered move preserves hidden slots and other operation types',async()=>{
 const h=setup();h.add('a','optimize');h.add('hidden','optimize','queued','two');h.add('up','upscale');h.add('b','optimize');h.run("queueLibrary='one';waitingSelection.add('b')");
 const controls=h.run("queueLaneSelection('optimize')");await controls.children.find(e=>e.textContent==='Move to top').onclick();
 assert.equal(h.calls[0].endpoint,'queue/change');assert.equal(h.calls[0].data.order.join(','),'b,hidden,up,a');assert.equal(h.calls[0].data.scope,'all');
});
test('drag refuses cross-lane targets and submits the snapshot captured before polling',async()=>{
 const h=setup();h.add('a','optimize');h.add('up','upscale');h.add('b','optimize');h.context.card=new Element('article');h.context.handle=new Element('button');
 h.run("queueDrag(card,handle,state.tasks[0])");const handle=h.context.handle;handle.onpointerdown({preventDefault(){},clientX:0,clientY:0,pointerId:1});h.target('up');handle.onpointerup({clientX:10,clientY:10});assert.equal(h.calls.length,0);
 handle.onpointerdown({preventDefault(){},clientX:0,clientY:0,pointerId:1});h.state.global_queue=[{id:'b',version:2},{id:'up',version:1},{id:'a',version:1}];h.target('b');await handle.onpointerup({clientX:10,clientY:10});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.calls[0].data.expected[0].id,'a');assert.equal(h.calls[0].data.expected[2].version,1);
});
test('file reordering has no removal action and uses the full file snapshot',async()=>{
 const h=setup();h.state.file_jobs=[{id:'f1',title:'First',phase:'waiting',library:'one'},{id:'hidden',title:'Hidden',phase:'waiting',library:'two'},{id:'f2',title:'Second',phase:'waiting',library:'one'}];h.state.file_queue=h.state.file_jobs.map(j=>({id:j.id,updated:'original'}));h.run("queueLibrary='one';queueFileSelection.add('f2')");
 const controls=h.run("queueLaneSelection('file_operations')");assert.equal(controls.children.some(e=>e.textContent==='Remove from queue'),false);
 await controls.children.find(e=>e.textContent==='Move to top').onclick();assert.equal(h.calls[0].endpoint,'file-queue/order');assert.equal(h.calls[0].data.order.join(','),'f2,hidden,f1');assert.equal(h.calls[0].data.expected.length,3);
});
test('ready link preserves artwork review visibility instead of sending it to the video-only inbox',()=>{
 const h=setup();h.add('art','artwork','awaiting_review');h.context.prepareInspector=()=>true;h.context.closeInspector=()=>{};h.context.setScreen=value=>h.calls.push({screen:value});
 h.run('renderQueueStatusLinks()');h.elements.get('queue-status-links').children.find(e=>e.textContent==='Ready to review 1').onclick();assert.equal(h.calls[0].screen,'processing');assert.equal(h.context.queueStatus,'awaiting_review');
});

test('queued joins stay in the file lane and retain task-order controls',async()=>{
 const h=setup();h.add('join1','join');h.add('encode','optimize');h.add('join2','join');
 const sections=h.run('renderProcessing()'),file=sections[0].children[2];assert.equal(sections.length,1);
 assert.equal(all(file).filter(e=>e.className.includes('queue-head')).length,1);assert.ok(h.cards.includes('join1'));assert.ok(h.cards.includes('join2'));
 h.run("waitingSelection.add('join2')");const controls=h.run("queueLaneSelection('join')");await controls.children.find(e=>e.textContent==='Move to top').onclick();
 assert.equal(h.calls[0].endpoint,'queue/change');assert.equal(h.calls[0].data.order.join(','),'join2,encode,join1');
});
test('join publication transfers ownership to file job without double counting',()=>{
 const h=setup();h.add('join','join','publishing');h.state.file_jobs=[{id:'publish',phase:'running',operation:'publish',title:'Join',library:'one',payload:{task:'join'}}];
 const board=h.run('renderProcessing()')[0];assert.equal(board.children.length,3);assert.equal(h.run('queueCountRows().length'),1);assert.equal(h.cards.includes('join'),false);
});
test('unowned interrupted cleanup remains visible once without replacing the board',()=>{
 const h=setup();h.state.cleanup_jobs=[{id:'orphan',phase:'interrupted',library:'one'},{id:'owned',phase:'deleting',library:'one'}];h.state.file_jobs=[{id:'cleanup',phase:'running',operation:'backup_cleanup',title:'Cleanup',library:'one',payload:{receipt:'owned'}}];
 const sections=h.run('renderProcessing()'),ids=all(sections[0]).filter(e=>e.dataset.cleanupId).map(e=>e.dataset.cleanupId);
 assert.equal(sections[0].children.length,3);assert.deepEqual(ids,['orphan']);assert.equal(h.run('queueCountRows().length'),2);
});

test('mixed artwork and video review remains visible in the processing review filter',()=>{
 const h=setup();h.add('art','artwork','awaiting_review');h.add('enc','optimize','awaiting_review');h.add('joined','join','awaiting_review');h.context.queueStatus='awaiting_review';
 const sections=h.run('renderProcessing()');assert.equal(sections[0].children.length,3);assert.equal(sections.length,2);assert.deepEqual(new Set(h.cards),new Set(['art','enc','joined']));
});
