// Run: npm install --no-save jsdom && node tests/viva-sorte.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'sites/realizafimdeano1.vercel.app/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'sites/realizafimdeano1.vercel.app/lottery.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
async function fixture() {
  const dom = new JSDOM(html, {url:'https://realizafimdeano1.vercel.app/', runScripts:'outside-only', virtualConsole:new VirtualConsole()});
  const requests = [];
  dom.window.HTMLElement.prototype.scrollIntoView = function() {};
  dom.window.fetch = async (url, options) => {
    assert.equal(url, '/__mock/events');
    requests.push(JSON.parse(options.body));
    return {ok:true};
  };
  dom.window.eval(script);
  await tick();
  return {dom, w:dom.window, requests};
}
function fill(w, name, value) {
  const el=w.document.querySelector(`[name="${name}"]`);
  el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}));
}
function submit(w) {w.document.querySelector('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));}
(async () => {
  const {dom,w,requests}=await fixture();
  assert.equal(w.document.querySelectorAll('script').length,1);
  assert.equal(w.document.querySelector('script').getAttribute('src'),'/lottery.js');
  fill(w,'full_name','Teste Pesquisa');fill(w,'cpf','00000000000');fill(w,'phone','11000000000');
  assert.equal(w.document.querySelector('[name="cpf"]').value,'000.000.000-00');
  submit(w);await tick();
  assert.equal(requests.filter(x=>x.type==='simulated_request').length,0,'Consent is required');
  w.document.querySelector('[name="consent"]').checked=true;
  submit(w);submit(w);await tick();await tick();
  const sent=requests.filter(x=>x.type==='simulated_request');
  assert.equal(sent.length,1,'Double submit must not duplicate submission');
  assert.deepEqual(sent[0].payload,{full_name:'Teste Pesquisa',cpf:'000.000.000-00',phone:'(11) 00000-0000',consent:true});
  assert.equal(sent[0].destination_verified,false);
  assert.equal(w.location.href,'https://realizafimdeano1.vercel.app/');
  assert.equal(w.document.querySelector('.successText h2').textContent,'Parabéns, Teste!');
  assert.equal(w.document.querySelector('form'),null);
  const link=w.document.querySelector('.quotaButton');link.click();await tick();
  assert.equal(w.location.href,'https://realizafimdeano1.vercel.app/');
  assert.equal(w.document.querySelector('#mock-quota-status').hidden,true);
  assert.equal(requests.at(-1).type,'blocked_navigation');
  assert.equal(requests.at(-1).target,'https://v0-renato.vercel.app/');
  assert.ok(requests.every(x=>x.external_sent===false));
  dom.window.close();
  const failed=await fixture();
  fill(failed.w,'full_name','Teste Pesquisa');fill(failed.w,'cpf','00000000000');fill(failed.w,'phone','11000000000');
  failed.w.document.querySelector('[name="consent"]').checked=true;
  failed.w.fetch=async()=>({ok:false});
  submit(failed.w);await tick();await tick();
  assert.ok(failed.w.document.querySelector('form'),'Failed logging must not show confirmation');
  assert.equal(failed.w.document.querySelector('#mock-error').hidden,true);
  failed.dom.window.close();
  console.log('PASS: registration validation, formatting, double-submit guard, same-URL confirmation, blocked link, fail-closed logging');
})().catch(error=>{console.error(error);process.exitCode=1;});
