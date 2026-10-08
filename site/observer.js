let events=[];
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function render(){const host=document.querySelector('#log');host.replaceChildren();if(!events.length){host.append(node('p','아직 제출된 정보가 없습니다. 실험 화면에서 Continue를 누르면 여기에 표시됩니다.'));return;}
for(const e of events.filter(e=>!document.querySelector('#site-filter').value||e.site_host===document.querySelector('#site-filter').value)){const card=node('section','');card.className='card';card.append(node('h2',e.stage==='email'?'이메일 제출':'비밀번호 제출'));
card.append(node('p','실험 사이트: '+(e.site_host||'이전 기록')));card.append(node('p','전송 대상: '+e.target));card.append(node('p','시각: '+e.time+' · 외부 전송 없음'));
const note=e.stage==='password'?'원본 전송 경로 미확인: 아래는 mock에서 제출한 값이며, 원본에서 실제 전송되는 항목으로 확정할 수 없습니다.':'원본 코드에서 확인한 전송 필드의 모의 기록입니다. 실제 원본 요청을 캡처한 결과는 아닙니다.';card.append(node('p',note));
const table=document.createElement('table');const tr=document.createElement('tr');tr.append(node('th','정보'),node('th','값'));table.append(tr);
for(const [k,v] of Object.entries(e.payload||{})){const row=document.createElement('tr');row.append(node('td',k),node('td',typeof v==='object'?JSON.stringify(v):String(v)));table.append(row);}card.append(table);host.append(card);}}
async function update(){try{const r=await fetch('/__mock/events');if(!r.ok)throw Error();const all=await r.json();const next=all.filter(e=>e.type==='simulated_request');if(JSON.stringify(next)!==JSON.stringify(events)){events=next;render();}document.querySelector('#status').textContent=`${events.length}건 · 로컬 기록 연결됨`;}catch{document.querySelector('#status').textContent='로컬 서버 연결 끊김';}}
setInterval(update,800);render();update();
document.querySelector('#clear').onclick=async()=>{await fetch('/__mock/events',{method:'DELETE'});await update();};
document.querySelector('#export').onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify({note:'Simulated submission fields, not captured original network traffic',events},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='submitted-information.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};

let sites=[];
function drawSites(){const box=document.querySelector('#sites');box.replaceChildren();for(const s of sites){const card=node('section','');card.className='card';card.append(node('h2',s.title));const a=node('a','실험 화면 열기 · '+s.host);a.href=document.querySelector('#scheme').value+'://'+s.host+s.entry;a.target='_blank';a.rel='noopener';card.append(a);box.append(card);}}
fetch('/__mock/sites').then(r=>r.json()).then(data=>{sites=data;for(const s of sites){const o=node('option',s.host);o.value=s.host;document.querySelector('#site-filter').append(o);}drawSites();}).catch(()=>{document.querySelector('#sites').textContent='사이트 목록을 불러오지 못했습니다.';});
document.querySelector('#scheme').onchange=drawSites;document.querySelector('#site-filter').onchange=render;
