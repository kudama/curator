'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function setup(){const calls=[],opened=[],saved=new Map();const c=vm.createContext({state:{tasks:[{id:'one',asset:'a',version:1,library:'one',kind:'optimize',status:'awaiting_review',title:'Match'},{id:'two',asset:'b',version:1,library:'two',kind:'upscale',status:'awaiting_review',title:'Other'}],global_queue:[]},libraryId:'one',searchText:'match',openedTask:'one',localStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)},catalogIndex:()=>({byId:new Map()}),prepareInspector:()=>true,api:async(endpoint,data)=>{calls.push({endpoint,data});return {id:'session',version:1,cursor:0,items:[{id:'one',version:1,decision:'pending'}]};},openTask:async id=>opened.push(id),closeInspector:()=>{},setScreen:()=>{},toast:()=>{},Promise});
 vm.runInContext(source,c);c.setScreen=()=>{};c.prepareInspector=()=>true;
 return {c,calls,opened,saved,run:code=>vm.runInContext(code,c)};}
test('new continuous session snapshots only visible matching result versions',async()=>{
 const h=setup();await h.run('startContinuousReview(false)');assert.equal(h.calls[0].endpoint,'review-session/open');assert.equal(h.calls[0].data.tasks.length,1);assert.equal(h.calls[0].data.tasks[0].id,'one');assert.equal(h.calls[0].data.tasks[0].version,1);assert.equal(h.saved.get('curator.review-session'),'session');assert.deepEqual(h.opened,['one']);
});
test('resume uses the saved identity and never submits a publication',async()=>{
 const h=setup();h.saved.set('curator.review-session','saved');await h.run('startContinuousReview(true)');assert.equal(h.calls.length,1);assert.equal(h.calls[0].data.id,'saved');assert.equal(h.calls[0].endpoint,'review-session/open');
});
test('shortcuts ignore typing, repeated keys and disabled accept controls',()=>{
 const h=setup();h.run("currentReviewSession={id:'session',cursor:0,items:[{id:'one'}]}");let clicks=0,prevented=0;const control={disabled:false,click(){clicks++;}};h.c.$=()=>({querySelector:()=>control});
 const event=extra=>({key:'a',target:{closest:()=>false},preventDefault(){prevented++;},...extra});
 h.c.event=event({target:{closest:()=>true}});h.run('handleReviewShortcut(event)');h.c.event=event({repeat:true});h.run('handleReviewShortcut(event)');control.disabled=true;h.c.event=event({});h.run('handleReviewShortcut(event)');assert.equal(clicks,0);
 control.disabled=false;h.c.event=event({});h.run('handleReviewShortcut(event)');assert.equal(clicks,1);assert.equal(prevented,1);
});
