'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){Object.assign(this,{tag,textContent:text,className:cls,children:[],value:'',hidden:false,disabled:false,checked:false,attrs:{}});}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(key,value){this.attrs[key]=value;}
}
const all=root=>[root,...root.children.filter(n=>n instanceof Element).flatMap(all)];
function setup(){
 const ids=Object.fromEntries(['task-detail','task-buttons','task-title','task-kind','task-reason'].map(k=>[k,new Element('div')])),calls=[],timers=[];
 const asset={id:'one',library:'lib',plex_path:'/media/Title/film.mp4'},context=vm.createContext({Set,JSON,state:{libraries:[{id:'lib',title:'Synthetic library'}]},libraryId:'lib',openedTask:null,inspectorMode:null,inspectorDirty:false,
  node:(...a)=>new Element(...a),$:id=>ids[id],button:(title,fn,cls)=>{const e=new Element('button',title,cls);e.onclick=fn;return e;},clientId:()=> 'fixture',prepareInspector:()=>true,showInspector(){},closeInspector(){context.openedTask=null;},selectedManagementFiles:()=>[asset],libraryFiles:()=>[asset],setTimeout:fn=>timers.push(fn),refresh:async()=>{},toast(){},api:async(endpoint,data)=>{calls.push({endpoint,data});return {};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/nfo-export.js'),'utf8'),context);
 return {context,ids,calls,timers,run:code=>vm.runInContext(code,context),find:title=>[...all(ids['task-detail']),...all(ids['task-buttons'])].find(n=>n.textContent===title),nodes:()=>[...all(ids['task-detail']),...all(ids['task-buttons'])]};
}
function manifest(){return {id:'plan',phase:'ready',assets:['one'],review_revision:'pinned',items:[{asset:'one',title:'Family film',phase:'ready',source_revision:'snapshot',warnings:['Cast portrait omitted explicitly'],files:[{kind:'nfo',name:'film.nfo',directory:'/media/Title',sha256:'new-hash',existing:{sha256:'old-hash'},bytes:5,action:'update',content:'<movie/>',owned:true}]}]};}
test('opening export prepares no writes and shows explicit scope',async()=>{
 const h=setup();await h.run('openNfoExport()');assert.equal(h.calls.length,0);assert.ok(h.find('Prepare preview'));assert.ok(h.find('Scope'));assert.ok(h.find('Recent exports'));
});
test('approval pins manifest revision, keeps updates opt-in, closes after durable queue',async()=>{
 const h=setup();h.context.record=manifest();h.context.panel=h.run("nfoPanel('Review')");await h.run('showNfoManifest(panel,record)');
 const approve=h.find('Approve & queue export');assert.ok(approve);assert.equal(approve.disabled,false);await approve.onclick();assert.equal(h.calls.length,1);assert.equal(h.calls[0].endpoint,'nfo/queue');assert.equal(h.calls[0].data.revision,'pinned');assert.equal(h.calls[0].data.updates.length,0);assert.equal(h.context.openedTask,null);
});
test('existing update checkbox is separate and a repeated click cannot queue twice',async()=>{
 const h=setup();h.context.record=manifest();h.context.panel=h.run("nfoPanel('Review')");await h.run('showNfoManifest(panel,record)');
 const update=h.nodes().find(n=>n.attrs['aria-label']==='Approve existing NFO update for Family film');update.checked=true;update.onchange();
 let finish;h.context.api=async(endpoint,data)=>{h.calls.push({endpoint,data});return new Promise(resolve=>finish=resolve);};
 const approve=h.find('Approve & queue export'),pending=approve.onclick();await approve.onclick();assert.equal(h.calls.length,1);assert.equal(h.calls[0].data.updates[0],'one');finish({});await pending;
});
test('late preparation result cannot replace another opened panel',async()=>{
 const h=setup();h.context.record={...manifest(),phase:'preparing',items:[]};h.context.panel=h.run("nfoPanel('Review')");await h.run('showNfoManifest(panel,record)');assert.equal(h.timers.length,1);h.context.openedTask='another';await h.timers[0]();assert.equal(h.calls.length,0);
});
test('partial receipt shows verified outcomes, omissions and fresh retry only',async()=>{
 const h=setup(),record=manifest();record.phase='partial';record.items[0].phase='failed';record.items[0].error='Source changed';record.items[0].files[0].outcome={state:'created',sha256:'new-hash'};h.context.record=record;h.context.panel=h.run("nfoPanel('Results')");await h.run('showNfoManifest(panel,record)');assert.ok(h.find('Prepare failed / partial items again'));assert.ok(h.find('Source changed'));assert.ok(h.find('NFO · created'));assert.equal(h.find('Approve & queue export'),undefined);
});
