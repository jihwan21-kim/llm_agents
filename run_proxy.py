import asyncio
from pathlib import Path
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster
from proxy_app import MockProxy
from browser_mail import MAIL_URL
async def main():
 opts=Options(listen_host='127.0.0.1',listen_port=8080,confdir=str(Path(__file__).resolve().parent/'mitm-ca'))
 master=DumpMaster(opts)
 master.options.update(connection_strategy='lazy',upstream_cert=False,stream_large_bodies=None,body_size_limit='1m')
 master.addons.add(MockProxy())
 print('Start page in the dedicated proxy browser:',MAIL_URL,flush=True)
 print('Research manager: http://mock.test/ | Mail clicks: http://mock.test/__mock/mail-events',flush=True)
 print('No upstream connections or live email providers are used.',flush=True)
 await master.run()
if __name__=='__main__':
 try:asyncio.run(main())
 except KeyboardInterrupt:pass
