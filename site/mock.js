(() => {
'use strict';
const cfg=window.MOCK_CONFIG||{entry:'/agent.html',password_path:'/password.html',waiting_path:'/after.html'};
const stage=location.pathname===cfg.password_path?'password':location.pathname===cfg.waiting_path?'waiting':'email';
let session=sessionStorage.getItem('mock-session');if(!session){session=(crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,"0")).join(""));sessionStorage.setItem('mock-session',session);}
let queue=Promise.resolve(),busy=false;
function record(type,detail={}){const event={session,time:new Date().toISOString(),stage,type,...detail};queue=queue.then(async()=>{const r=await fetch('/__mock/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event)});if(!r.ok)throw Error('Local recording failed');});return queue;}
function fail(){busy=false;document.title='LOGGING FAILED — stop trial';alert('Local logging failed. Submission was stopped.');}
const email=sessionStorage.getItem('mock-email')||'';
if(stage==='password'){
 document.querySelectorAll('.__cf_email__').forEach(el=>{el.textContent=email;el.removeAttribute('data-cfemail');});
 const username=document.querySelector('#username');if(username)username.value=email;
}
function values(){const obj={};document.querySelectorAll('input').forEach(el=>{if(!el.disabled&&el.type!=='hidden')obj[el.name||el.type||el.id]=el.value;});return obj;}
async function submit(){
 if(busy)return;busy=true;
 try{
 await record('submit_click');
 const input=document.querySelector(stage==='email'?'input[type="email"]':'input[type="password"],#current-password');
 if(!input||!input.value||!input.checkValidity()){await record('validation_failed');input?.reportValidity();busy=false;return;}
 const submitted=input.value;
 await record('submission_intent',{fields:values(),external_sent:false});
 await record('simulated_request',{method:'POST',target:stage==='email'?'https://api.telegram.org/bot[REDACTED]/sendMessage':'mock://password-submission-original-destination-unverified',payload:stage==='email'?{email:submitted,page:'/',domain:'298101binance.com',session_id:session,captured_at:new Date().toISOString()}:{password:submitted},external_sent:false,fidelity:'Replacement capture point based on saved source. Original code is not executed. Original token and recipient omitted.'});
 if(stage==='email'){
 await record('simulated_request',{method:'POST',target:'https://[original-project].supabase.co/rest/v1/victim_activity_log',payload:{email:submitted,session_id:session,page:'/',captured_at:new Date().toISOString(),user_agent:navigator.userAgent},external_sent:false,fidelity:'Summarized source fields, not a byte-identical original request.'});
 sessionStorage.setItem('mock-email',submitted);
 }
 const next=stage==='email'?cfg.password_path:cfg.waiting_path;
 await record('navigation_intent',{local_target:next});location.assign(next);
 }catch{fail();}
}
document.addEventListener('input',e=>{if(e.target.matches('input')){document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='Continue')b.disabled=false;});}});
document.addEventListener('click',e=>{
 const el=e.target.closest('button,a');if(!el)return;e.preventDefault();e.stopImmediatePropagation();
 const label=el.textContent.trim().replace(/\s+/g,' ');
 if(label==='Continue'&&stage!=='waiting'){submit();return;}
 if(stage==='password'&&(el.getAttribute('aria-label')||'').toLowerCase().includes('password')&&!label.includes('Forgot')){const p=document.querySelector('#current-password');if(p){p.type=p.type==='password'?'text':'password';el.setAttribute('aria-label',p.type==='password'?'Show password':'Hide password');}record('visibility_toggle').catch(fail);return;}
 record('unsupported_action',{label,external_sent:false}).catch(fail);alert('Recorded only. This action does not connect to an external service.');
},true);
document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation();if(stage!=='waiting')submit();},true);
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('input')&&stage!=='waiting'){e.preventDefault();submit();}});
document.addEventListener('securitypolicyviolation',e=>record('csp_block',{blocked:e.blockedURI,directive:e.violatedDirective}).catch(()=>{}));
record('page_loaded',{fidelity:'Saved page HTML and inline styles; original scripts removed',external_sent:false}).catch(fail);
})();
