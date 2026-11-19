'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.dataset={};this.attrs={};this.style={};}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}setAttribute(k,v){this.attrs[k]=v;}
 get classList(){return {toggle:(cls,on)=>{if(on)this.className+=' '+cls;}};}
}
function setup(){
 const elements=new Map(),calls=[];let allow=true;
 const assets=[{id:'a',library:'one',title:'First',plex_path:'/synthetic/First.mp4',item:{},fingerprint:{size:10}},{id:'b',library:'one',title:'Second',plex_path:'/synthetic/Second.mp4',item:{},fingerprint:{size:20}},{id:'other',library:'two',title:'Other',plex_path:'/else/Other.mp4',item:{}}];
 const state={assets,libraries:[{id:'one',title:'One'},{id:'two',title:'Two'}],tasks:[]};
 const context=vm.createContext({state,libraryId:'one',screen:'library',libraryView:'attention',filter:'all',searchText:'',selectedAssetId:null,selected:new Set(),inspectorDirty:true,TASK_LABELS:{metadata:'Metadata',upscale:'Upscaling'},
  $:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},node:(...args)=>new Element(...args),button:(text,fn,cls)=>{const e=new Element('button',text,cls);e.onclick=fn;return e;},
  catalogIndex:()=>({byId:new Map(assets.map(a=>[a.id,a])),byAsset:new Map(assets.map(a=>[a.id,state.tasks.filter(t=>t.asset===a.id)]))}),
  render(){},refresh:async()=>calls.push({refresh:true}),toast:text=>calls.push({message:text}),taskAvailable:()=>true,featureAvailable:()=>false,taskControls:()=>new Element('div'),formatBytes:String,run:fn=>fn(),
  api:()=>{throw Error('Navigation and selection must not mutate the server');}});
 for(const name of ['workbench','file-management'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/'+name+'.js'),'utf8'),context);
 context.prepareInspector=()=>allow;context.closeInspector=()=>calls.push({close:true});context.openTask=id=>calls.push({task:id});context.openAssetOverview=id=>calls.push({overview:id});context.openFileOperation=async(asset,kind,ids)=>calls.push({operation:kind,asset:asset.id,ids});
 const add=(id,kind='metadata')=>{const task={id,kind,asset:'a',library:'one',status:'recommendation',version:1};state.tasks.push(task);return task;};
 return {context,state,assets,calls,elements,add,allow:value=>{allow=value;},run:code=>vm.runInContext(code,context)};
}
test('File management navigation respects unsaved edits and opens no operation',()=>{
 const h=setup();h.allow(false);assert.equal(h.run("setScreen('filemanagement')"),false);assert.equal(h.context.screen,'library');
 h.allow(true);assert.equal(h.run("setScreen('filemanagement')"),true);assert.equal(h.context.screen,'filemanagement');assert.equal(h.calls.some(c=>c.operation),false);
});
test('the library Queue link changes only the view scope and clears waiting selection',()=>{
 const h=setup();h.run("queueLibrary='all';waitingSelection.add('other-library-task')");
 assert.equal(h.run("setScreen('processing',true)"),true);
 assert.equal(h.run('queueLibrary'),'one');assert.equal(h.run('waitingSelection.size'),0);
 assert.equal(h.calls.some(c=>c.operation),false);
});
test('declining unsaved edits leaves the queue scope and selection unchanged',()=>{
 const h=setup();h.allow(false);h.run("queueLibrary='all';waitingSelection.add('keep')");
 assert.equal(h.run("setScreen('processing',true)"),false);
 assert.equal(h.run('queueLibrary'),'all');assert.equal(h.run('waitingSelection.has("keep")'),true);
 assert.equal(h.context.screen,'library');
});
test('library change keeps the file workspace, clears selection and can be refused',()=>{
 const h=setup();h.context.screen='filemanagement';h.run("fileManagementSelection.add('a')");h.allow(false);
 assert.equal(h.run("chooseFileManagementLibrary('two')"),false);assert.equal(h.context.libraryId,'one');assert.equal(h.run('fileManagementSelection.size'),1);
 h.allow(true);assert.equal(h.run("chooseFileManagementLibrary('two')"),true);assert.equal(h.context.screen,'filemanagement');assert.equal(h.context.libraryId,'two');assert.equal(h.run('fileManagementSelection.size'),0);
});
test('join passes only the explicitly selected files in the current library',async()=>{
 const h=setup();h.run("fileManagementSelection.add('a');fileManagementSelection.add('b');fileManagementSelection.add('other')");await h.run("launchFileManagement('join')");
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].operation,'join');assert.equal(h.calls[0].ids.join(','),'a,b');
 h.calls.length=0;await h.run("launchFileManagement('rename')");assert.equal(h.calls.length,0);
});
test('hidden selections are disclosed, and checking a row does not open a tool',()=>{
 const h=setup();h.run("fileManagementSelection.add('a');fileManagementSelection.add('b')");h.context.searchText='first';assert.match(h.run('fileManagementSelectionText()'),/2 selected · 1 hidden/);
 const row=h.run('renderFileManagement()')[0],check=row.children[0];check.checked=false;check.onchange();assert.equal(h.run("fileManagementSelection.has('a')"),false);assert.equal(h.calls.some(c=>c.operation),false);
});
test('clicking a filename opens its rename preview form directly',async()=>{
 const h=setup(),row=h.run('renderFileManagement()')[0];await row.children[2].children[0].onclick();
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].operation,'rename');assert.equal(h.calls[0].asset,'a');assert.equal(h.calls.some(c=>c.overview),false);
});
test('task grouping opens the exact task without an overview or selection side effect',async()=>{
 const h=setup();h.add('metadata');h.add('upscale','upscale');h.context.selected.add('unrelated');
 await h.run("openGroupedTask('a','upscale')");assert.deepEqual(h.calls,[{task:'upscale'}]);assert.deepEqual([...h.context.selected],['unrelated']);
});
test('a stale grouped row refreshes instead of opening an unrelated task',async()=>{
 const h=setup();h.add('gone').status='resolved';h.add('unrelated','upscale');await h.run("openGroupedTask('a','metadata')");assert.ok(h.calls.some(c=>c.refresh));assert.equal(h.calls.some(c=>c.task||c.overview),false);
});
test('multiple plans require an explicit choice instead of choosing one arbitrarily',async()=>{
 const h=setup();h.add('art1','artwork');h.add('art2','artwork');await h.run("openGroupedTask('a','artwork')");assert.deepEqual(h.calls,[{overview:'a'}]);
});
test('clicking the queue card surface opens the task, while controls do not double-open it',()=>{
 const h=setup(),task=h.add('blocked');task.status='blocked';h.context.task=task;const card=h.run('processingTaskCard(task)');
 card.onclick({target:{closest:()=>null}});assert.deepEqual(h.calls,[{task:'blocked'}]);card.onclick({target:{closest:()=>({})}});assert.equal(h.calls.length,1);
});
