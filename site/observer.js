let events=[];
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function render(){const host=document.querySelector('#log');host.replaceChildren();if(!events.length){host.append(node('p','No submissions yet. Select Continue on an experiment page to see them here.'));return;}
for(const e of events.filter(e=>!document.querySelector('#site-filter').value||e.site_host===document.querySelector('#site-filter').value)){const card=node('section','');card.className='card';card.append(node('h2',e.stage==='email'?'Email submission':'Password submission'));
card.append(node('p','Experiment site: '+(e.site_host||'Legacy event')));card.append(node('p','Simulated destination: '+e.target));card.append(node('p','Time: '+e.time+' · No external transmission'));
const note=e.stage==='password'?'Original destination unverified: these values were submitted in the mock. They are not confirmed fields from an original outbound request.':'Simulated record of submission fields identified in the saved source. This is not a capture of an original network request.';card.append(node('p',note));
const table=document.createElement('table');const tr=document.createElement('tr');tr.append(node('th','Field'),node('th','Value'));table.append(tr);
for(const [k,v] of Object.entries(e.payload||{})){const row=document.createElement('tr');row.append(node('td',k),node('td',typeof v==='object'?JSON.stringify(v):String(v)));table.append(row);}card.append(table);host.append(card);}}
async function update(){try{const r=await fetch('/__mock/events');if(!r.ok)throw Error();const all=await r.json();const next=all.filter(e=>e.type==='simulated_request');if(JSON.stringify(next)!==JSON.stringify(events)){events=next;render();}document.querySelector('#status').textContent=`${events.length} records · Local logging connected`;}catch{document.querySelector('#status').textContent='Local server disconnected';}}
setInterval(update,800);render();update();
document.querySelector('#clear').onclick=async()=>{await fetch('/__mock/events',{method:'DELETE'});await update();};
document.querySelector('#export').onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify({note:'Simulated submission fields, not captured original network traffic',events},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='submitted-information.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};

let sites=[];
function drawSites(){const box=document.querySelector('#sites');box.replaceChildren();for(const s of sites){const card=node('section','');card.className='card';card.append(node('h2',s.title));const a=node('a','Open experiment · '+s.host);a.href=document.querySelector('#scheme').value+'://'+s.host+s.entry;a.target='_blank';a.rel='noopener';card.append(a);box.append(card);}}
fetch('/__mock/sites').then(r=>r.json()).then(data=>{sites=data;for(const s of sites){const o=node('option',s.host);o.value=s.host;document.querySelector('#site-filter').append(o);}drawSites();}).catch(()=>{document.querySelector('#sites').textContent='Unable to load the site list.';});
document.querySelector('#scheme').onchange=drawSites;document.querySelector('#site-filter').onchange=render;

