'use strict';
let refreshFlight=null,refreshAgain=false,stateRevision='',refreshTimer=null,refreshFailures=0,presenceDue=0;
function connectionStatus(failed){
 const status=$('connection-status');status.hidden=!failed;
 status.textContent=failed?'Connection interrupted. Showing the last update; reconnecting automatically.':'';
}
function applyStateUpdate(update){
 if(update.reset)return update.state;
 const next={...state,...update.fields};
 for(const [key,change] of Object.entries(update.changes)){
  const rows=new Map(state[key].map(row=>[row.id,row]));
  for(const id of change.removed)rows.delete(id);
  for(const row of change.upsert)rows.set(row.id,row);
  next[key]=change.order?change.order.map(id=>rows.get(id)):[...rows.values()];
 }
 return next;
}
function refresh(){
 if(serviceRestarting)return Promise.resolve();
 if(refreshFlight){refreshAgain=true;return refreshFlight;}
 refreshFlight=(async()=>{
  do{
   refreshAgain=false;const epoch=mutationEpoch,controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
   let update;
   try{
    const response=await fetch('/api/state/updates'+(stateRevision?'?since='+encodeURIComponent(stateRevision):''),{signal:controller.signal});
    if(!response.ok)throw Error('Refresh unavailable ('+response.status+')');
    update=await response.json();
   }catch(error){connectionStatus(true);throw error;}finally{clearTimeout(timeout);}
   // A user action completed during this read; discard its potentially stale response.
   if(epoch!==mutationEpoch){refreshAgain=true;continue;}
   if(serviceRestarting)return;
   state=applyStateUpdate(update);stateRevision=update.revision;connectionStatus(false);
   if(!libraryId&&state.libraries.length)libraryId=state.libraries[0].id;
   render();updateServiceControls();
  }while(refreshAgain&&!serviceRestarting);
 })().finally(()=>{refreshFlight=null;});
 return refreshFlight;
}
async function backgroundRefresh(){
 try{
  await refresh();refreshFailures=0;
  if(Date.now()>=presenceDue){presenceDue=Date.now()+60000;await syncCatalog();}
 }catch(error){refreshFailures++;connectionStatus(true);}
 finally{refreshTimer=setTimeout(backgroundRefresh,Math.min(60000,4000*2**Math.min(refreshFailures,4)));}
}
function startBackgroundRefresh(){clearTimeout(refreshTimer);backgroundRefresh();}
