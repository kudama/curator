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
test('publication is counted once and unsupported types retain the existing queue',()=>{
 const h=setup();h.add('publication','optimize','publishing');h.state.file_jobs=[{id:'file',phase:'running',operation:'publish',title:'Publication',library:'one',payload:{task:'publication'}}];
 assert.equal(h.run('queueCountRows().length'),1);h.run('renderProcessing()');assert.equal(h.cards.includes('publication'),false);
 h.add('metadata','metadata');assert.equal(h.run('queueBoardAvailable()'),false);assert.equal(h.run('renderProcessing()')[0],'legacy');
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
