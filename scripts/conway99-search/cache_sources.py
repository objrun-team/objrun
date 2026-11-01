import urllib.request,hashlib,json,concurrent.futures
from pathlib import Path
from html.parser import HTMLParser
root=Path(__file__).resolve().parents[2];run=Path((root/'data/conway99-search/latest-run.txt').read_text().strip())
sources={
 'alco418':'https://alco.centre-mersenne.org/articles/10.5802/alco.418/',
 'alco418-pdf':'https://alco.centre-mersenne.org/item/10.5802/alco.418.pdf',
 'sat-v2':'https://arxiv.org/html/2604.23037v2',
 'forced-v2':'https://arxiv.org/html/2608.11211v2',
 'spanning-v2':'https://arxiv.org/html/2610.16266v2'}
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,s):self.parts.append(s)
 def handle_starttag(self,t,attrs):
  if t=='math':self.parts.append(dict(attrs).get('alttext',''))
def get(item):
 name,url=item
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:raw=r.read();status=r.status
  suffix='.pdf' if raw.startswith(b'%PDF') else '.html';p=run/'sources'/(name+suffix);p.write_bytes(raw)
  if suffix=='.html':
   parser=Parser();parser.feed(raw.decode('utf-8'));(run/'reference'/(name+'.txt')).write_text('\n'.join(parser.parts),encoding='utf-8')
  return {'name':name,'url':url,'status':status,'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()}
 except Exception as e:return {'name':name,'url':url,'error':str(e),'fallback':'Browser search indexed primary source; source unavailable for full cache.'}
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:result=list(pool.map(get,sources.items()))
(run/'sources/manifest.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
