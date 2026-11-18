'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/app.js'),'utf8');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.attrs={};this.dataset={};this.hidden=true;}
 append(...items){for(const item of items){item.parent=this;this.children.push(item);}}
 remove(){this.parent.children=this.parent.children.filter(item=>item!==this);}
 setAttribute(key,value){this.attrs[key]=value;}
}
function setup(){
 const elements=new Map(),calls=[];let inspecting=false;
 const context=vm.createContext({$:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},node:(...args)=>new Element(...args),
  button:(text,fn,cls)=>{const e=new Element('button',text,cls);e.onclick=fn;return e;},inspectorOpen:()=>inspecting,
  api:async(endpoint,data)=>{calls.push({endpoint,data});return {id:'task',version:2,status:data.action==='delete'?'queued':'recommendation'};},
  selected:new Set(),refresh:async()=>{},openedTask:null,inspectorMode:null,closeInspector(){},run:fn=>fn()});
 vm.runInContext(source.slice(source.indexOf('function feedbackTarget'),source.indexOf('async function api')),context);
 vm.runInContext(source.slice(source.indexOf('async function taskAction'),source.indexOf('function taskControls')),context);
 return {elements,calls,context,inspect:()=>{inspecting=true;},run:code=>vm.runInContext(code,context)};
}
test('feedback goes beside the active workspace or editor, with no overlay or timeout',()=>{
 const h=setup();h.run("toast('Queued')");assert.equal(h.elements.get('workspace-feedback').children[0].children[0].textContent,'Queued');
 h.inspect();h.run("toast('Review error',true)");assert.equal(h.elements.get('task-feedback').children[0].attrs.role,'alert');
 h.elements.get('config-dialog').open=true;h.run("toast('Settings error',true)");assert.equal(h.elements.get('config-feedback').children.length,1);
 assert.equal(h.elements.has('toast'),false);
});
test('errors and actions survive later successes until explicitly dismissed',()=>{
 const h=setup(),error=h.run("toast('Failed',true)");h.run("toast('Another job queued')");
 const feedback=h.elements.get('workspace-feedback');assert.equal(feedback.children.length,2);assert.equal(feedback.children[0],error);
 error.children.find(e=>e.textContent==='Dismiss').onclick();assert.equal(feedback.children.length,1);assert.equal(feedback.hidden,false);
 feedback.children[0].children.find(e=>e.textContent==='Dismiss').onclick();assert.equal(feedback.hidden,true);
});
test('delete Undo stays available after another notice and uses the returned version',async()=>{
 const h=setup();await h.run("taskAction({id:'task',version:1,status:'queued'},'delete')");
 const notice=h.elements.get('workspace-feedback').children[0],undo=notice.children.find(e=>e.textContent==='Undo');assert.ok(undo);
 h.run("toast('Another queue action finished')");assert.ok(h.elements.get('workspace-feedback').children.includes(notice));
 await undo.onclick();assert.equal(h.calls[1].data.action,'restore_task');assert.equal(h.calls[1].data.version,2);
});
test('feedback from one task does not appear as a new task error',()=>{
 const h=setup();h.inspect();h.context.openedTask='first';const old=h.run("toast('First task failed',true)");
 h.context.openedTask='second';const current=h.run("toast('Second task saved')");assert.equal(old.hidden,true);assert.equal(current.hidden,false);
 current.children.find(e=>e.textContent==='Dismiss').onclick();assert.equal(h.elements.get('task-feedback').hidden,true);
});
