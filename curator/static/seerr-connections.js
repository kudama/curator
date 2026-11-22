/* Read-only, supported-unconfigured surface; this never signs in or starts a sync. */
async function prepareSeerrConnection(){
 const section=$('seerr-connection');if(!section)return;section.replaceChildren(node('h3','Seerr requests'));
 const status=await api('seerr/status');section.append(node('p',status.message),node('p','Connection is off. Review the instance, verified version and a dedicated view-only account before connecting.','muted'));
 for(const [label,placeholder,type] of [['Server URL','Not selected','url'],['View-only account','Not selected','text']]){const input=node('input');input.type=type;input.disabled=true;input.placeholder=placeholder;section.append(previewField(label,input));}
 const connect=button('Connect after review',()=>{},'subtle');connect.disabled=true;section.append(connect,node('p','No API key, credential or session is stored. No requests are created or changed.','muted'));
}
function renderSeerrArrivals(target,view){
 target.replaceChildren(node('h2','Requests that landed'));
 if(!view.enabled){target.append(node('p',view.message),button('Connection settings',openConfig,'text-button'));return;}
 if(view.stale)target.append(node('p','Showing the last complete update.','muted'));
 for(const row of view.rows||[]){if(!row.recent&&['landed','partly_landed','ambiguous'].includes(row.state))continue;if(!['landed','partly_landed','ambiguous','available_not_scanned'].includes(row.state))continue;const box=node('article');box.append(node('p',({landed:'In Plex',partly_landed:'Some episodes in Plex',ambiguous:'Multiple Plex matches',available_not_scanned:'Available, not yet scanned'})[row.state]));for(const match of row.matches||[])box.append(button(match.title,()=>{if(!chooseLibrary(match.library))return;if(setScreen('library')===false)return;run(()=>openAssetOverview(match.asset));},'text-button'));target.append(box);}
}
