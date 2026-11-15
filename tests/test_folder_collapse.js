'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');

function workspace(overrides={}){
 const groups=[{open:true},{open:true}];
 const context=vm.createContext({libraryId:'one',screen:'library',activeGrouping:'folder',
  state:{folders:[{id:'folder-one',library:'one'},{id:'folder-two',library:'two'}],
   assets:[{library:'one',plex_path:'/media/unlisted/file.mkv'},{library:'two',plex_path:'/other/movie.mkv'}]},
  selectedAssetId:'selected-file',inspectorDirty:true,
  document:{querySelectorAll(selector){assert.equal(selector,'#tasks details.file-group');return groups;}},
  api(){throw Error('Unexpected backend call');},render(){throw Error('Unexpected rerender');},...overrides});
 vm.runInContext(source,context);
 return {groups,context,run:code=>vm.runInContext(code,context)};
}

test('collapses rendered and non-rendered folder keys only for the current library',()=>{
 const w=workspace();w.run('collapseAllFolders()');
 assert.ok(w.groups.every(group=>!group.open));
 assert.equal(w.run("collapsedGroups.has('one:folder:folder-one')"),true);
 assert.equal(w.run("collapsedGroups.has('one:folder:/media/unlisted')"),true);
 assert.equal(w.run("collapsedGroups.has('one:folder:folder-two')"),false);
 assert.equal(w.run("collapsedGroups.has('one:folder:/other')"),false);
 assert.equal(w.run("rememberGroup({},'two:folder:folder-two').open"),true);
 assert.equal(w.run("rememberGroup({},'one:processing:Waiting').open"),true);
});

test('persists through rerender and allows a single folder to be reopened',()=>{
 const w=workspace();w.run('collapseAllFolders()');
 assert.equal(w.run("rememberGroup({},'one:folder:folder-one').open"),false);
 w.run("const reopened=rememberGroup({},'one:folder:folder-one');reopened.open=true;reopened.ontoggle()");
 assert.equal(w.run("rememberGroup({},'one:folder:folder-one').open"),true);
 assert.equal(w.run("rememberGroup({},'one:folder:/media/unlisted').open"),false);
});

test('preserves review state, selection and catalog data without a backend request',()=>{
 const w=workspace(),before=JSON.stringify(w.context.state);w.run('collapseAllFolders()');
 assert.equal(w.context.selectedAssetId,'selected-file');
 assert.equal(w.context.inspectorDirty,true);
 assert.equal(JSON.stringify(w.context.state),before);
});

test('does nothing outside folder views or without a library',()=>{
 for(const overrides of [{screen:'processing'},{screen:'history'},{activeGrouping:'movie'},{activeGrouping:'task'},{libraryId:null}]){
  const w=workspace(overrides);w.run('collapseAllFolders()');
  assert.ok(w.groups.every(group=>group.open));assert.equal(w.run('collapsedGroups.size'),0);
 }
});

test('handles catalogs whose folder list has not yet been populated',()=>{
 const w=workspace({state:{assets:[{library:'one',plex_path:'/media/file.mkv'}]}});
 w.run('collapseAllFolders()');assert.equal(w.run("collapsedGroups.has('one:folder:/media')"),true);
});
