'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function setup(){const c=vm.createContext({});vm.runInContext(source,c);return code=>vm.runInContext(code,c);}
test('history includes failures and excludes waiting/active/recommendations',()=>{
 const run=setup();for(const status of ['applied','resolved','rejected','cancelled','blocked','failed'])assert.equal(run(`historyStatusMatches({status:'${status}'})`),true);
 for(const status of ['recommendation','queued','running','publishing','awaiting_review'])assert.equal(run(`historyStatusMatches({status:'${status}'})`),false);
});
test('each filter is exact and Completed includes applied and resolved',()=>{
 const run=setup();run("historyStatus='completed'");assert.equal(run("historyStatusMatches({status:'applied'})"),true);assert.equal(run("historyStatusMatches({status:'resolved'})"),true);assert.equal(run("historyStatusMatches({status:'cancelled'})"),false);
 for(const status of ['cancelled','rejected','failed','blocked']){run(`historyStatus='${status}'`);assert.equal(run(`historyStatusMatches({status:'${status}'})`),true);assert.equal(run("historyStatusMatches({status:'applied'})"),false);}
});
