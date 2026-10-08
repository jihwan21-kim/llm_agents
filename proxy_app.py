"""Serve only saved mock pages. Never open an upstream server connection."""
from pathlib import Path
import json,base64
from datetime import datetime,timezone
from mitmproxy import http
ROOT=Path(__file__).resolve().parent
HOST='mock.test'
SITES={s['host']:s for s in json.loads((ROOT/'sites.json').read_text(encoding='utf-8'))['sites']}
class MockProxy:
 def __init__(self):
  self.events=[]
  self.logdir=ROOT/'logs';self.logdir.mkdir(exist_ok=True)
  self.logfile=self.logdir/('requests-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.jsonl')
 def server_connect(self,data):
  data.server.error='Research mock: all upstream connections denied'
 def requestheaders(self,flow):
  flow.request.stream=False
 def reply(self,flow,status,body=b'',mime='application/json'):
  flow.response=http.Response.make(status,body,{'Content-Type':mime,'Cache-Control':'no-store','X-Mock-Proxy':'local-only','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'self'; form-action 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
 def record_request(self,flow,outcome):
  q=flow.request
  row={'time':datetime.now(timezone.utc).isoformat(),'method':q.method,'url':q.pretty_url,'headers':list(q.headers.items(multi=True)),'body_base64':base64.b64encode(q.raw_content or b'').decode(),'body_text':q.get_text(strict=False),'outcome':outcome,'upstream_sent':False}
  with self.logfile.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 def request(self,flow):
  try:self.handle(flow)
  except Exception:
   self.reply(flow,500,b'{"error":"local processing failed; upstream denied"}')
 def handle(self,flow):
  q=flow.request
  path=q.path.split('?',1)[0]
  if q.host not in {HOST,*SITES} or q.port not in (80,443):
   self.record_request(flow,'blocked');return self.reply(flow,403,b'{"blocked":true,"upstream_sent":false}')
  if q.headers.get('Origin') not in (None,'http://'+q.host,'https://'+q.host):
   return self.reply(flow,403)
  if q.headers.get('Upgrade'):
   self.record_request(flow,'upgrade_blocked');return self.reply(flow,403)
  if q.host==HOST and path=='/__mock/sites' and q.method=='GET':
   return self.reply(flow,200,json.dumps([{'id':s['id'],'title':s['title'],'host':s['host'],'entry':s['entry']} for s in SITES.values()]).encode())
  if path=='/__mock/events':
   if q.method=='GET' and q.host==HOST:return self.reply(flow,200,json.dumps(self.events).encode())
   if q.method=='DELETE' and q.host==HOST:self.events.clear();return self.reply(flow,200,b'{}')
   if q.method=='POST' and q.host in SITES:
    if len(q.raw_content or b'')>65536:return self.reply(flow,413)
    data=json.loads(q.get_text())
    if not isinstance(data,dict):return self.reply(flow,400)
    self.record_request(flow,'mock_event_recorded')
    data['site_host']=q.host;data['site_id']=SITES[q.host]['id']
    self.events.append(data);del self.events[:-1000]
    return self.reply(flow,200,b'{"recorded":true,"external_sent":false,"via":"mitmproxy"}')
  mapping={'/':'index.html','/observer.js':'observer.js'} if q.host==HOST else SITES[q.host]['routes']
  if q.method=='GET' and path in mapping:
   self.record_request(flow,'local_file')
   name=mapping[path]
   folder=(ROOT/('main' if q.host==HOST else SITES[q.host]['directory'])).resolve()
   file=(folder/name).resolve()
   if not file.is_relative_to(ROOT.resolve()):return self.reply(flow,403)
   body=file.read_bytes()
   if q.host in SITES and path=='/mock.js':
    cfg=SITES[q.host]
    body=('window.MOCK_CONFIG='+json.dumps({'entry':cfg['entry'],'password_path':cfg['password_path'],'waiting_path':cfg['waiting_path']})+';\n').encode()+body
   return self.reply(flow,200,body,'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/html; charset=utf-8')
  self.record_request(flow,'unmapped_blocked');self.reply(flow,403,b'{"blocked":true,"upstream_sent":false}')
