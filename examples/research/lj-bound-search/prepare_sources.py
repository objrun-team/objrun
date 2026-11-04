from pathlib import Path
import datetime, json, hashlib, subprocess, urllib.request
ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'data/lj-bound-search'
BASE.mkdir(exist_ok=True)
pointer=BASE/'latest-run.txt'
if pointer.exists():
    RUN=Path(pointer.read_text().strip())
else:
    RUN=BASE/('run-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    RUN.mkdir()
    pointer.write_text(str(RUN))
for n in ('reference','checker','baseline','work','verified','requests','jobs','engine','final','proof'):
    (RUN/n).mkdir(exist_ok=True)
sources={
 'kiessling-wales-2511.15008.html':'https://arxiv.org/html/2511.15008',
 'yuhjtman-1501.05248v2.pdf':'https://arxiv.org/pdf/1501.05248v2',
 'vinko-2005.pdf':'https://cyber.bibl.u-szeged.hu/index.php/actcybern/article/download/3657/3641',
 'schachinger-addis-bomze-schoen-2005.pdf':'https://optimization-online.org/wp-content/uploads/2005/06/1151.pdf',
 'xue-1997.pdf':'https://link.springer.com/content/pdf/10.1023/A:1008284629099.pdf',
}
records=[]
for name,url in sources.items():
    p=RUN/'reference'/name
    rec={'file':name,'url':url,'access_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        if not p.exists():
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=45) as r:
                raw=r.read();rec['final_url']=r.url
            if name.endswith('.pdf') and not raw.startswith(b'%PDF'):raise ValueError('not PDF')
            p.write_bytes(raw)
        rec['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        rec['bytes']=p.stat().st_size
        if name.endswith('.pdf'):
            subprocess.run(['pdftotext','-layout',str(p),str(p.with_suffix('.txt'))],check=True,capture_output=True)
    except Exception as e:rec['error']=str(e)
    records.append(rec)
(RUN/'reference/sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print(json.dumps({'run':str(RUN),'sources':records},indent=2))
