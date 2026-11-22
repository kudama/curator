'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// A minimal DOM: enough for the inspector to render and for tests to find text and controls.
class El{constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.className='';this.attrs={};this.disabled=false;this.hidden=false;}
 append(...kids){for(const k of kids)this.children.push(typeof k==='string'?Object.assign(new El('#text'),{textContent:k}):k);}
 replaceChildren(...kids){this.children=[];this.append(...kids);}
 replaceWith(){}setAttribute(k,v){this.attrs[k]=v;}
 all(){return this.children.flatMap(c=>[c,...c.all()]);}
 querySelectorAll(){return this.all().filter(c=>c.tag==='button'||c.tag==='input');}
 text(){return [this.textContent,...this.children.map(c=>c.text())].join(' ');}}
function setup(view,{confirmAnswer=true}={}){
 const calls=[],els={};const $=id=>els[id]||(els[id]=new El('div'));
 const context=vm.createContext({URLSearchParams,calls,
  $,document:{createTextNode:t=>Object.assign(new El('#text'),{textContent:t})},
  node:(tag,text,cls)=>{const e=new El(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;},
  button:(text,fn,cls)=>{const e=new El('button');e.textContent=text;e.onclick=fn;e.className=cls||'';return e;},
  api:async(p,data)=>{calls.push({p,data});if(!data)return structuredClone(view);if(p.endsWith('restore-artwork'))return {tasks:['t1'],already:[],receipt:view};return view;},
  prepareInspector:()=>true,showInspector:()=>{},closeInspector:()=>{},openTask:()=>{},confirm:()=>confirmAnswer,
  openedTask:null,inspectorMode:null,structuredClone});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/rename-receipts.js'),'utf8'),context);
 return {context,calls,detail:$('task-detail'),run:code=>vm.runInContext(code,context)};
}
const VIEW={id:'a'.repeat(24),title:'Sample Film',asset:'asset-1',library:'lib',status:'review',version:'v1',cast_digest:'d1',renamed:{before:'Old.mkv',after:'New.mkv'},rematched:true,rolled_back:false,
 metadata:[{field:'summary',captured:'Before',current:'',state:'differs'},{field:'title',captured:'T',current:'T',state:'retained'}],
 metadata_restore:{state:'proposed',task:'meta-1',fields:['summary']},
 artwork:[{kind:'cover',bytes:10,verified:true,state:'changed',restore:null,can_restore:true},{kind:'background',bytes:10,verified:true,state:'retained',restore:null,can_restore:false}],
 portraits:[{index:0,name:'Person',role:'Self',retained:'retained',verified:true,state:'changed',restore:null,can_restore:true},{index:1,name:'Guest',role:'',retained:'reference'}]};
const buttons=(h,label)=>h.detail.all().filter(e=>e.tag==='button'&&e.textContent===label);
const checks=h=>h.detail.all().filter(e=>e.tag==='input');
test('opening a receipt only reads it and explains what changed',async()=>{
 const h=setup(VIEW);await h.run(`openRenameReceipt('${VIEW.id}')`);
 assert.deepEqual(h.calls.map(c=>c.data),[undefined]);
 const text=h.detail.text();
 for(const phrase of ['Something changed after the rename','Renamed from Old.mkv to New.mkv','Before the rename: Before','Plex now shows a different image','Plex shows a different picture','Plex can fetch it again','changes nothing'])assert.ok(text.includes(phrase),phrase);
 assert.equal(checks(h).length,2);// Only the changed poster and the changed picture can be chosen.
 assert.equal(buttons(h,'Create restore review')[0].disabled,true);
});
test('artwork restore sends the reviewed version and only the chosen kinds',async()=>{
 const h=setup(VIEW);await h.run(`openRenameReceipt('${VIEW.id}')`);
 const [art]=checks(h);art.checked=true;art.onchange();
 await buttons(h,'Create restore review')[0].onclick();
 const post=h.calls.find(c=>c.data);assert.equal(post.p,'rename/receipt/restore-artwork');
 assert.equal(JSON.stringify(post.data),JSON.stringify({id:VIEW.id,version:'v1',kinds:['cover']}));
 assert.ok(h.detail.text().includes('waiting in Artwork'));
});
test('declining the picture confirmation sends nothing; accepting sends people and the cast digest',async()=>{
 let h=setup(VIEW,{confirmAnswer:false});await h.run(`openRenameReceipt('${VIEW.id}')`);
 let person=checks(h)[1];person.checked=true;person.onchange();buttons(h,'Restore selected pictures')[0].onclick();
 await new Promise(r=>setTimeout(r,0));assert.equal(h.calls.filter(c=>c.data).length,0);
 h=setup(VIEW);await h.run(`openRenameReceipt('${VIEW.id}')`);
 person=checks(h)[1];person.checked=true;person.onchange();buttons(h,'Restore selected pictures')[0].onclick();
 await new Promise(r=>setTimeout(r,0));
 const post=h.calls.find(c=>c.data);assert.equal(post.p,'rename/receipt/restore-portraits');
 assert.equal(JSON.stringify(post.data),JSON.stringify({id:VIEW.id,version:'v1',people:[0],cast_digest:'d1'}));
});
test('a failed restore is shown and the receipt is read again',async()=>{
 const h=setup(VIEW);h.context.api=async(p,data)=>{h.calls.push({p,data});if(data)throw Error('Plex now matches a different file to this item; rescan first. Nothing was restored.');return structuredClone(VIEW);};
 await h.run(`openRenameReceipt('${VIEW.id}')`);const [art]=checks(h);art.checked=true;art.onchange();
 await buttons(h,'Create restore review')[0].onclick();
 assert.ok(h.detail.text().includes('Nothing was restored'));assert.equal(h.calls.filter(c=>!c.data).length,2);
});
