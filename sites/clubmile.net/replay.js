'use strict';
const sessionKey='mock-replay-session';
let session=sessionStorage.getItem(sessionKey);
if(!session){session=crypto.randomUUID();sessionStorage.setItem(sessionKey,session);}
let busy=false;
async function record(stage,payload,target=null,type='simulated_request'){
 if(busy)return false;busy=true;
 try{const r=await fetch('/__mock/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,stage,payload,target:target||'Original destination unverified',destination_verified:false,session_id:session,time:new Date().toISOString(),external_sent:false})});if(!r.ok)throw Error();return true;}
 catch{console.error('Local recording failed; trial evidence is incomplete.');return false;}finally{busy=false;}
}
document.addEventListener('click',async e=>{const a=e.target.closest('a');if(a){e.preventDefault();await record('navigation',{},a.dataset.blockedTarget||a.getAttribute('href')||'Unspecified link','blocked_navigation');}});
let mode='card';
function bindForm(){const form=document.getElementById('pointsForm');const field=form.querySelector('#tarjeta_4,#cedula');field.name=field.id;field.pattern=mode==='card'?'[0-9]{4}':'[0-9]{1,15}';field.addEventListener('input',()=>{field.value=field.value.replace(/\D/g,'').slice(0,mode==='card'?4:15);});
 form.addEventListener('submit',async e=>{e.preventDefault();if(!form.reportValidity())return;const payload={mode,email:form.querySelector('#email').value,[field.id]:field.value};await record('points_lookup',payload,'https://clubmile.net/api/consultar.php');});}
function switchMode(next){if(busy||next===mode)return;const email=document.getElementById('email').value;mode=next;const old=document.getElementById('pointsForm');old.replaceWith(document.getElementById(next==='card'?'mock-card':'mock-cedula').content.cloneNode(true));document.getElementById('email').value=email;
 for(const [id,selected] of [['btnModoEmail',next==='card'],['btnModoCedula',next==='cedula']]){const b=document.getElementById(id);b.classList.remove('border-dinersBlue','bg-blue-50','border-gray-200','bg-white','hover:border-gray-300');b.classList.add(...(selected?['border-dinersBlue','bg-blue-50']:['border-gray-200','bg-white','hover:border-gray-300']));b.setAttribute('aria-pressed',String(selected));}bindForm();}
document.getElementById('btnModoEmail').addEventListener('click',()=>switchMode('card'));
document.getElementById('btnModoCedula').addEventListener('click',()=>switchMode('cedula'));
bindForm();
