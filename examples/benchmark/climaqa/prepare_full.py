"""Freeze the 225 validated ClimaQA MCQs not included in the 20-question pilot."""
import csv, hashlib, io, json, re, urllib.request
from pathlib import Path
from prepare import REV, URL, EXPECTED
ROOT=Path(__file__).resolve().parents[3]
PILOT=ROOT/'docs/climaqa/pilot-20261028-v1'
OUT=ROOT/'docs/climaqa/full-20261028-v1'
def main():
 if OUT.exists():raise RuntimeError('FullDirectoryExistsInspectFirst')
 raw=urllib.request.urlopen(URL,timeout=30).read();assert hashlib.sha256(raw).hexdigest()==EXPECTED
 allrows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));rows=[x for x in allrows if x['Validation']=='True']
 assert len(allrows)==292 and len(rows)==245
 pilot=json.loads((PILOT/'public.json').read_text(encoding='utf-8')); excluded={x['source_row'] for x in pilot};assert len(excluded)==20
 pub=[];private=[]
 for row in rows:
  if int(row['']) in excluded:continue
  parts=re.split(r'\s*-{20}\s*',row['Options'].strip())
  assert len(parts)==4 and all(re.match(r'^'+x+r'\)',p.strip(),re.I) for x,p in zip('abcd',parts)) and row['Answer'] in 'abcd'
  tid='climaqa-gold-mcq-'+row[''].zfill(3)
  prompt='Answer the following climate science multiple-choice question. Choose exactly one option. End your response with exactly one line: Answer: X, where X is A, B, C, or D.\n\n'+row['Question']+'\n\n'+row['Options']
  pub.append({'id':tid,'source_row':int(row['']),'complexity':row['Complexity'],'prompt':prompt});private.append({'id':tid,'answer':row['Answer'].upper()})
 assert len(pub)==225 and len({x['id'] for x in pub})==225
 OUT.mkdir(parents=True)
 for name,obj in [('public.json',pub),('private.json',private),('source.json',{'url':URL,'revision':REV,'sha256':EXPECTED,'allRows':292,'validated':245,'pilotIds':[x['id'] for x in pilot],'remainingIds':[x['id'] for x in pub],'selection':'all validated rows not in frozen pilot; original CSV order'})]:
  (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'remaining':len(pub),'pilot':len(pilot),'total':245,'revision':REV}))
if __name__=='__main__':main()
