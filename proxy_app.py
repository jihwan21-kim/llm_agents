"""Serve saved mock pages while allowing explicitly listed agent service hosts upstream."""
from pathlib import Path
import json,base64
from datetime import datetime,timezone
from urllib.parse import urlsplit
from mitmproxy import http
from browser_mail import MAIL_HOST, MAIL_URL, BrowserMailbox, serve_static
ROOT=Path(__file__).resolve().parent
HOST='mock.test'
# Explicit service allowlist, not a wildcard for all Google-owned domains.
AGENT_API_HOSTS={
 'api.openai.com', 'cdn.platform.openai.com', 'chatgpt.com', 'api.anthropic.com',
 'claude.ai', 'platform.claude.com', 's-cdn.anthropic.com',
 'assets-proxy.anthropic.com', 'bridge.claudeusercontent.com',
 'accounts.google.com', 'oauth2.googleapis.com', 'www.googleapis.com',
 'ssl.gstatic.com', 'www.gstatic.com', 'translate.googleapis.com',
}
# Explicit browser auth/background endpoints; these hosts are not
# general-purpose live browsing exceptions.
_READ_METHODS=frozenset({'GET','HEAD'})
_POST_METHODS=frozenset({'POST','OPTIONS'})
BROWSER_BACKGROUND_ROUTES={
 # Chrome's token minting and device-bound session discovery use different
 # hosts from accounts.google.com. Both must pass for the sign-in flow.
 'oauthaccountmanager.googleapis.com': {'/v1/issuetoken': _POST_METHODS,
                                       '/v1/upgradetoken': _POST_METHODS},
 'google.com': {'/.well-known/device-bound-sessions': _READ_METHODS},
 'www.google.com': {'/async/folae': _READ_METHODS,
                    '/.well-known/device-bound-sessions': _READ_METHODS},
 'update.googleapis.com': {'/service/update2/json': _POST_METHODS},
 'ab.chatgpt.com': {'/v1/rgstr': _POST_METHODS,
                    '/v1/sdk_exception': _POST_METHODS},
 'o33249.ingest.us.sentry.io': {
  '/api/4512228274601984/envelope/': _POST_METHODS},
 'csp.withgoogle.com': {'/csp/report-to/gse_qebhlk': _POST_METHODS},
 'browser-intake-us5-datadoghq.com': {'/api/v2/rum': _POST_METHODS},
 **{host: {'/domainreliability/upload': _POST_METHODS} for host in (
  'beacons.gcp.gvt2.com', 'beacons3.gvt2.com', 'beacons4.gvt2.com',
  'beacons5.gvt2.com', 'beacons5.gvt3.com', 'clients2.google.com',
 )},
}
SITES={s['host']:s for s in json.loads((ROOT/'sites.json').read_text(encoding='utf-8'))['sites']}
class MockProxy:
 def __init__(self):
  self.events=[]
  self.mail_events=[]
  self.mailbox=BrowserMailbox(SITES.values())
  self.logdir=ROOT/'logs';self.logdir.mkdir(exist_ok=True)
  self.logfile=self.logdir/('requests-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.jsonl')
 def local_hosts(self):
  hosts={HOST,MAIL_HOST,*SITES,*getattr(self,'captures',{})}
  for name in ('capture','site'):
   host=getattr(getattr(self,name,None),'host',None)
   if host:hosts.add(host.lower())
  return hosts
 def allows_upstream(self,request):
  host=request.host.lower()
  local_hosts=self.local_hosts()
  if request.scheme!='https' or request.port!=443 or host in local_hosts:
   return False
  # Mock pages cannot send their form data or scripts to live services through
  # these exceptions. Calls from browser/extension origins remain supported.
  for header in ('Origin','Referer'):
   try:source=urlsplit(request.headers.get(header,'')).hostname
   except ValueError:return False
   if source and source.lower() in local_hosts:return False
  if host in AGENT_API_HOSTS:return True
  if request.headers.get('Upgrade'):return False
  methods=BROWSER_BACKGROUND_ROUTES.get(host,{}).get(request.path.split('?',1)[0],())
  return request.method in methods
 def server_connect(self,data):
  address=data.server.address
  host=(address[0] if address else '').lower()
  port=address[1] if address else None
  if (port==443 and host not in self.local_hosts() and
      (host in AGENT_API_HOSTS or host in BROWSER_BACKGROUND_ROUTES)):return
  data.server.error='Research mock: upstream host or port not allowed'
 def requestheaders(self,flow):
  flow.request.stream=False
 def reply(self,flow,status,body=b'',mime='application/json'):
  flow.response=http.Response.make(status,body,{'Content-Type':mime,'Cache-Control':'no-store','X-Mock-Proxy':'local-only','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'self'; form-action 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
 def record_request(self,flow,outcome):
  q=flow.request
  row={'time':datetime.now(timezone.utc).isoformat(),'method':q.method,'url':q.pretty_url,'headers':list(q.headers.items(multi=True)),'body_base64':base64.b64encode(q.raw_content or b'').decode(),'body_text':q.get_text(strict=False),'outcome':outcome,'upstream_sent':False}
  with self.logfile.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 def log_mail_event(self,kind,message_id):
  row={'time':datetime.now(timezone.utc).isoformat(),
       'kind':kind,'message_id':message_id,
       'upstream_sent':False,'synthetic_inbox':True}
  if kind=='link_click':
   row['target_host']=self.mailbox.resolve(message_id).split('/')[2]
  self.mail_events.append(row)
  del self.mail_events[:-1000]
  with self.logfile.open('a',encoding='utf-8') as f:
   f.write(json.dumps(row)+'\n')
 def request(self,flow):
  if self.allows_upstream(flow.request):
   return  # Forward the real response; do not fabricate a successful reply.
  try:self.handle(flow)
  except Exception:
   self.reply(flow,500,b'{"error":"local processing failed; upstream denied"}')
 def handle(self,flow):
  q=flow.request
  path=q.path.split('?',1)[0]
  if q.host not in {HOST,MAIL_HOST,*SITES} or q.port not in (80,443):
   self.record_request(flow,'blocked');return self.reply(flow,403,b'{"blocked":true,"upstream_sent":false}')
  if q.headers.get('Origin') not in (None,'http://'+q.host,'https://'+q.host):
   return self.reply(flow,403)
  if q.headers.get('Upgrade'):
   self.record_request(flow,'upgrade_blocked');return self.reply(flow,403)
  # Browser-only mailbox (ordinary GETs, no email provider or mailbox server).
  # Unlike legacy form event logs, mail telemetry never saves raw request
  # bodies, cookies, headers, query strings or text entered on a page.
  if q.host==MAIL_HOST:
   if q.method not in ('GET','HEAD'):
    return self.reply(flow,405,b'{"error":"method_not_allowed"}')
   if path=='/api/messages':
    raw=json.dumps(self.mailbox.public_messages()).encode('utf-8')
    return self.reply(flow,200,raw if q.method=='GET' else b'')
   if path.startswith('/read/') and path.count('/')==2:
    mid=path[len('/read/'):]
    if not self.mailbox.resolve(mid):return self.reply(flow,404,b'{"error":"not_found"}')
    if q.method=='GET':self.log_mail_event('message_open',mid)
    return self.reply(flow,200,b'{}')
   if path.startswith('/open/') and path.count('/')==2:
    mid=path[len('/open/'):]
    destination=self.mailbox.resolve(mid)
    if destination is None:return self.reply(flow,404,b'{"error":"not_found"}')
    if q.method=='GET':self.log_mail_event('link_click',mid)
    self.reply(flow,302,b'', 'text/plain; charset=utf-8')
    flow.response.headers['Location']=destination
    return
   local=serve_static(path)
   if local:
    body,mime=local
    return self.reply(flow,200,body if q.method=='GET' else b'',mime)
   return self.reply(flow,404,b'{"error":"not_found"}')
  if q.host==HOST and path=='/__mock/mail-events':
   if q.method=='GET':
    return self.reply(flow,200,json.dumps(self.mail_events).encode('utf-8'))
   if q.method=='DELETE':
    self.mail_events.clear()
    return self.reply(flow,200,b'{}')
   return self.reply(flow,405,b'{"error":"method_not_allowed"}')
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

