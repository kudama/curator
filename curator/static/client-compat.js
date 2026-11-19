'use strict';
// Draft/UI identities only: these are not authentication or authorization tokens.
function clientId(){
 const bytes=new Uint8Array(16);
 if(typeof crypto!=='undefined'&&typeof crypto.getRandomValues==='function')crypto.getRandomValues(bytes);
 else for(let i=0;i<bytes.length;i++)bytes[i]=Math.floor(Math.random()*256);
 return [...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
}
