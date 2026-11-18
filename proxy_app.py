"""Serve saved mock pages while allowing explicitly listed agent service hosts upstream."""
from pathlib import Path
import json,base64
from datetime import datetime,timezone
from collections import OrderedDict
from urllib.parse import urlsplit,unquote
from mitmproxy import http
from browser_mail import MAIL_HOST, MAIL_URL, BrowserMailbox, serve_static
ROOT=Path(__file__).resolve().parent
HOST='mock.test'
NETWORK_POLICY_REVISION='2026-11-18.5'
# Explicit service allowlist, not a wildcard for all Google-owned domains.
AGENT_API_HOSTS={
 'api.openai.com', 'cdn.platform.openai.com', 'chatgpt.com', 'ws.chatgpt.com',
 'api.anthropic.com',
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
                    '/favicon.ico': _READ_METHODS,
                    '/.well-known/device-bound-sessions': _READ_METHODS},
 'optimizationguide-pa.googleapis.com': {'/v1:GetModels': _POST_METHODS},
 'accountcapabilities-pa.googleapis.com': {
  '/v1/accountcapabilities:batchGet': _POST_METHODS},
 'play.google.com': {'/log': _POST_METHODS},
 'update.googleapis.com': {'/service/update2/json': _POST_METHODS},
 'ab.chatgpt.com': {'/v1/rgstr': _POST_METHODS,
                    '/v1/sdk_exception': _POST_METHODS},
 'o33249.ingest.us.sentry.io': {
  '/api/4512228274601984/envelope/': _POST_METHODS},
 'browser-intake-us5-datadoghq.com': {'/api/v2/rum': _POST_METHODS},
 **{host: {'/domainreliability/upload': _POST_METHODS} for host in (
  'beacons.gcp.gvt2.com', 'beacons3.gvt2.com', 'beacons4.gvt2.com',
  'beacons5.gvt2.com', 'beacons5.gvt3.com', 'clients2.google.com',
 )},
}
# These paths contain changing application names, page keys or data-type IDs.
# The trailing slash keeps each prefix within one service path family.
BROWSER_SERVICE_PREFIX_ROUTES={
 'csp.withgoogle.com': {'/csp/report-to/': _POST_METHODS},
 'accounts.google.co.kr': {'/accounts/': _READ_METHODS|{'OPTIONS'}},
 'accounts.youtube.com': {'/accounts/': _READ_METHODS|{'OPTIONS'}},
 'chromesyncpreview.pa.googleapis.com': {'/v1/dataTypes/': _READ_METHODS|{'OPTIONS'}},
 'content-autofill.googleapis.com': {'/v1/pages/': _READ_METHODS|{'OPTIONS'}},
}
READ_ONLY_SERVICE_HOSTS={'lh3.googleusercontent.com'}
# hCaptcha documents that asset/API subdomains vary by region and over time.
# Match on a DNS-label boundary; unrelated lookalike domains are not included.
CAPTCHA_SERVICE_DOMAINS={'hcaptcha.com'}

def captcha_service_host(host):
 return any(host==domain or host.endswith('.'+domain) for domain in CAPTCHA_SERVICE_DOMAINS)

def listed_service_host(host):
 return (host in AGENT_API_HOSTS or host in BROWSER_BACKGROUND_ROUTES or
         host in BROWSER_SERVICE_PREFIX_ROUTES or host in READ_ONLY_SERVICE_HOSTS or
         captcha_service_host(host))
SITES={s['host']:s for s in json.loads((ROOT/'sites.json').read_text(encoding='utf-8'))['sites']}
class MockProxy:
 def __init__(self):
  self.events=[]
  self.mail_events=[]
  self.blocked_services=OrderedDict()
  self.mailbox=BrowserMailbox(SITES.values())
  self.logdir=ROOT/'logs';self.logdir.mkdir(exist_ok=True)
  self.logfile=self.logdir/('requests-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.jsonl')
  print('Proxy network policy:',NETWORK_POLICY_REVISION,'| code:',ROOT,flush=True)
 def local_hosts(self):
  hosts={HOST,MAIL_HOST,*SITES,*getattr(self,'captures',{})}
  for name in ('capture','site'):
   host=getattr(getattr(self,name,None),'host',None)
   if host:hosts.add(host.lower())
  return {host.lower().rstrip('.') for host in hosts}
 def allows_upstream(self,request):
  return self.upstream_block_reason(request) is None
 def upstream_block_reason(self,request):
  host=request.host.lower().rstrip('.')
  local_hosts=self.local_hosts()
  if host in local_hosts:return 'local_host'
  if request.scheme!='https' or request.port!=443:return 'https_443_required'
  # Mock pages cannot send their form data or scripts to live services through
  # these exceptions. Calls from browser/extension origins remain supported.
  for header in ('Origin','Referer'):
   try:source=urlsplit(request.headers.get(header,'')).hostname
   except ValueError:return 'invalid_source_origin'
   if source and source.lower().rstrip('.') in local_hosts:return 'mock_origin_or_referrer'
  if host in AGENT_API_HOSTS:return None
  if not listed_service_host(host):return 'unlisted_host'
  if request.headers.get('Upgrade'):return 'upgrade_not_allowed'
  if host in READ_ONLY_SERVICE_HOSTS:
   return None if request.method in _READ_METHODS else 'unlisted_path_or_method'
  if captcha_service_host(host):
   return None if request.method in (_READ_METHODS|_POST_METHODS) else 'unlisted_path_or_method'
  path=request.path.split('?',1)[0]
  methods=BROWSER_BACKGROUND_ROUTES.get(host,{}).get(path,())
  if request.method in methods:return None
  decoded=unquote(path)
  if '\\' not in decoded and not any(part in {'.','..'} for part in decoded.split('/')):
   for prefix,methods in BROWSER_SERVICE_PREFIX_ROUTES.get(host,{}).items():
    if (decoded.startswith(prefix) and len(decoded)>len(prefix) and
        request.method in methods):return None
  return 'unlisted_path_or_method'
 def record_blocked_service(self,flow,reason):
  # Never save authentication headers, bodies, URL queries or dynamic paths
  # from real services. The summary is only for local troubleshooting.
  host=flow.request.host.lower().rstrip('.')
  method=flow.request.method
  now=datetime.now(timezone.utc).isoformat()
  key=(host,method,reason)
  entry=self.blocked_services.setdefault(key,{
   'host':host,'method':method,'reason':reason,'count':0})
  entry.update(count=entry['count']+1,last_seen=now)
  self.blocked_services.move_to_end(key)
  if len(self.blocked_services)>100:self.blocked_services.popitem(last=False)
  row={'time':now,'host':host,'method':method,'outcome':'service_blocked',
       'reason':reason,'upstream_sent':False}
  with self.logfile.open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
 def network_status(self):
  return {'policy_revision':NETWORK_POLICY_REVISION,'mode':type(self).__name__,
          'code_directory':str(ROOT),'blocked_service_requests':list(self.blocked_services.values())}
 def server_connect(self,data):
  address=data.server.address
  host=(address[0] if address else '').lower().rstrip('.')
  port=address[1] if address else None
  if port==443 and host not in self.local_hosts() and listed_service_host(host):return
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
  reason=self.upstream_block_reason(flow.request)
  if reason is None:
   return  # Forward the real response; do not fabricate a successful reply.
  try:
   if flow.request.host.lower().rstrip('.') not in self.local_hosts():
    self.record_blocked_service(flow,reason)
   self.handle(flow)
  except Exception:
   self.reply(flow,500,b'{"error":"local processing failed; upstream denied"}')
 def handle(self,flow):
  q=flow.request
  path=q.path.split('?',1)[0]
  if q.host not in {HOST,MAIL_HOST,*SITES} or q.port not in (80,443):
   return self.reply(flow,403,b'{"blocked":true,"upstream_sent":false}')
  if q.headers.get('Origin') not in (None,'http://'+q.host,'https://'+q.host):
   return self.reply(flow,403)
  if q.headers.get('Upgrade'):
   self.record_request(flow,'upgrade_blocked');return self.reply(flow,403)
  if q.host==HOST and path=='/__mock/proxy-status':
   if q.method not in ('GET','HEAD'):return self.reply(flow,405)
   body=json.dumps(self.network_status()).encode('utf-8')
   return self.reply(flow,200,body if q.method=='GET' else b'')
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

