'use strict';
const sessionKey='mock-replay-session';
let session=sessionStorage.getItem(sessionKey);
if(!session){session=crypto.randomUUID();sessionStorage.setItem(sessionKey,session);}
let busy=false;
function status(text){let n=document.getElementById('mock-status');if(!n){n=document.createElement('p');n.id='mock-status';n.setAttribute('role','status');n.style.cssText='position:fixed;bottom:12px;left:12px;background:white;color:#222;padding:12px;z-index:99999';document.body.append(n);}n.textContent=text;}
async function record(stage,payload,target=null,type='simulated_request'){
 if(busy)return false;busy=true;
 try{const r=await fetch('/__mock/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,stage,payload,target:target||'Original destination unverified',destination_verified:false,session_id:session,time:new Date().toISOString(),external_sent:false})});if(!r.ok)throw Error();return true;}
 catch{status('Local logging failed. Submission was not completed.');return false;}finally{busy=false;}
}
document.addEventListener('click',async e=>{const a=e.target.closest('a');if(a){e.preventDefault();await record('navigation',{},a.dataset.blockedTarget||a.getAttribute('href')||'Unspecified link','blocked_navigation');status('Link recorded locally. No external page was opened.');}});
const modal=document.getElementById('mock-login');
const checkbox=document.querySelector('input[type=checkbox]');
const buttons=[...document.querySelectorAll('button')];
const named=text=>buttons.find(b=>b.textContent.trim()===text);
named('Continue with Facebook').addEventListener('click',()=>{if(!checkbox.checked){status('Please select the checkbox first.');return;}document.getElementById('mock-status')?.remove();modal.hidden=false;modal.querySelector('input').focus();});
modal.querySelector('button').addEventListener('click',()=>{modal.hidden=true;named('Continue with Facebook').focus();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.hidden){modal.hidden=true;named('Continue with Facebook').focus();}});
async function submit(){const email=modal.querySelector('[name=email_or_phone]'),password=modal.querySelector('[name=password]');if(!email.value.trim()||!password.value){status('Enter email or phone number and password.');return;}if(await record('login',{email_or_phone:email.value,password:password.value}))status('Recorded locally. Authentication is not simulated beyond this saved screen.');}
named('Log In').addEventListener('click',submit);
modal.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();submit();}});
for(const text of ['Forgot password?','Create new account'])named(text).addEventListener('click',async()=>{await record('navigation',{action:text},'Destination unavailable in snapshot','blocked_navigation');status('This action has no supplied replay screen. No external page was opened.');});
