"""Remove identified resource bodies embedded in JSON, preserving real textual evidence.

Only derived exports are written. Text fields are never shortened. Transformations
record original and exported hashes; original JSON byte identity is not claimed.
"""
import argparse,base64,collections,copy,gzip,json,os,pathlib,re
from records import Records
from export_records import Exporter,JsonShards,encoded,sha,magic,path_policy,reviewed_resource_match

PAYLOAD=re.compile(r'("(?:base64|rawBase64)"\s*:\s*")([A-Za-z0-9+/]{32,}={0,2})(")')
RESOURCE_KINDS={'binary','executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress'}

def transform(data,scrub,collection,changes,resources,depth=0):
    if depth>8:return data
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return data
    if not any(marker in text for marker in ('base64','rawBase64','"data"','PRIVATE KEY')) and 'bearer' not in text.lower():return data
    def payload(value,path,forced_reason=None):
        try:raw=base64.b64decode(value,validate=True)
        except (ValueError,TypeError):return value
        kind=magic(raw[:4096]);reason=forced_reason or path_policy(collection,path)
        if not forced_reason and raw.startswith(b'PACK\0'):reason='embedded-git-object-pack'
        if kind in RESOURCE_KINDS:reason=reason or 'embedded-binary-resource-'+kind
        if reason:
            item=dict(sha256=sha(raw),bytes=len(raw),kind=kind,path=path,reason=reason)
            resources.append(item);changes['embedded_resource_removal']+=1
            return '[RESOURCE_REMOVED bytes='+str(len(raw))+' sha256='+item['sha256']+' reason='+reason+']'
        if kind=='text':
            updated=transform(raw,scrub,collection,changes,resources,depth+1)
            decoded,redactions,_=scrub.text(updated.decode('utf-8'))
            if decoded!=updated.decode('utf-8'):changes.update(redactions)
            if updated!=raw or decoded!=updated.decode('utf-8'):
                changes['embedded_text_conversion']+=1
                exported=decoded.encode('utf-8')
                resources.append(dict(resource_removed=False,path=path,source_bytes=len(raw),source_sha256=sha(raw),exported_bytes=len(exported),exported_sha256=sha(exported),encoding='base64'))
                return base64.b64encode(exported).decode('ascii')
        return value
    def text_value(value):
        updated=value
        if value.lstrip().startswith(('{','[')):
            converted=transform(value.encode('utf-8'),scrub,collection,changes,resources,depth+1).decode('utf-8')
            if converted!=value:updated=converted;changes['nested_json_text_conversion']+=1
        cleaned,counts,removed=scrub.text(updated)
        if cleaned!=updated:changes.update(counts);resources.extend(removed)
        return cleaned
    def walk(value,pointer=''):
        if isinstance(value,dict):
            for key,child in value.items():
                location=pointer+'/'+key
                if key in ('base64','rawBase64') and isinstance(child,str):value[key]=payload(child,str(value.get('path',value.get('name',location))))
                elif key=='data' and isinstance(child,str) and value.get('op')=='append-f64' and 'offset' in value:value[key]=payload(child,location,'bulk-numeric-transfer-payload')
                elif key=='data' and isinstance(child,str) and '/state/' in pointer and pointer.rsplit('/',1)[-1].startswith(('model.','lm_head.')) and pointer.rsplit('/',1)[-1].endswith(('.weight','.bias')) and isinstance(value.get('shape'),list) and value.get('dtype'):value[key]=payload(child,location,'model-weight-tensor')
                elif isinstance(child,str):value[key]=text_value(child)
                else:walk(child,location)
        elif isinstance(value,list):
            for index,child in enumerate(value):
                if isinstance(child,str):value[index]=text_value(child)
                else:walk(child,pointer+'/'+str(index))
    before=sum(changes.values())
    try:
        document=json.loads(text);walk(document)
        if sum(changes.values())!=before:
            changes['json_reserialization']+=1
            try:return encoded(document)
            except ValueError:
                # Some native numerical logs use JSON NaN/Infinity. Preserve
                # these failure values while removing the reviewed resource.
                changes['nonfinite_json_preserved']+=1
                return json.dumps(document,ensure_ascii=True,separators=(',',':'),allow_nan=True).encode('ascii')
        return data
    except (ValueError,RecursionError):
        if '\n' in text:
            lines=text.splitlines(keepends=True);changed=False;output=[]
            for line in lines if len(lines)>1 else []:
                if line.lstrip().startswith('{'):
                    converted=transform(line.encode('utf-8'),scrub,collection,changes,resources,depth+1).decode('utf-8')
                    if line.endswith('\n') and not converted.endswith('\n'):converted+='\n'
                    changed=changed or converted!=line;output.append(converted)
                else:output.append(line)
            if changed:return ''.join(output).encode('utf-8')
        # stdout can contain multiple JSON objects or ordinary surrounding text.
        updated=PAYLOAD.sub(lambda m:m[1]+payload(m[2],'')+m[3],text)
        return updated.encode('utf-8') if updated!=text else data

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','workspace','work'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    ap.add_argument('--rules',type=pathlib.Path)
    ap.add_argument('--resource-hashes',type=pathlib.Path)
    a=ap.parse_args();r=Records(a.source);assert not a.output.exists()
    rules=json.loads(a.rules.read_text(encoding='utf-8')) if a.rules else []
    resource_hashes=json.loads(a.resource_hashes.read_text(encoding='utf-8')) if a.resource_hashes else {}
    for rule in rules:rule['_regex']=re.compile(rule['pattern'],re.I)
    x=Exporter(argparse.Namespace(workspace=a.workspace,output=a.output,work=a.work,compression_level=6));x.store.prefix='embedded-text'
    streams={};audit=JsonShards(a.output,'embedded-transformations');cache={};count=0;removed=0
    def rewrite(v,collection,path,bench):
        nonlocal count,removed
        if not isinstance(v,dict):return
        if reviewed_resource_match(v,resource_hashes):return
        if any((not q.get('collection') or q['collection']==collection) and q['_regex'].search(path) for q in rules):return
        table='exported_rows' in v and 'columns' in v
        if (v.get('format')=='text' or table) and v.get('content',{}).get('bytes',0)>0:
            c=v['content'];key=(c['sha256'],collection,table)
            if key not in cache:
                raw=b''.join(r.parts(c));changes=collections.Counter();resources=[]
                updated=transform(raw,x.scrub,collection,changes,resources)
                text,redactions,removed_resources=x.scrub.text(updated.decode('utf-8'))
                if text!=updated.decode('utf-8'):changes.update(redactions);resources.extend(removed_resources)
                updated=text.encode('utf-8')
                if table and raw.endswith(b'\n') and not updated.endswith(b'\n'):updated+=b'\n'
                cache[key]=(x.store.put(updated,bench),dict(changes),resources) if updated!=raw else None
            result=cache[key]
            if result:
                content,changes,resources=result;v['content']=content
                v.setdefault('transformations',{}).update(changes)
                audit.write(dict(collection=collection,path=path,input_content_sha256=c['sha256'],output_content_sha256=content['sha256'],changes=changes,resources=[z for z in resources if z.get('resource_removed',True)],embedded_text_conversions=[z for z in resources if not z.get('resource_removed',True)]));count+=1;removed+=sum(z.get('bytes',0) for z in resources if z.get('resource_removed',True))
        for m in v.get('members',[]):rewrite(m,collection,path+'!/'+m['path'],bench)
        for t in v.get('tables',[]):rewrite(t,collection,path+'!table/'+t['name'],bench)
    for e in r.entries():
        rewrite(e,e['collection'],e['path'],e['bench']);streams.setdefault(e['collection'],JsonShards(a.output,e['collection'])).write(e)
    x.store.finish()
    for name in r.packs:os.link(r.root/name,a.output/name)
    (a.output/'manifests/packs.json').write_bytes(encoded(list(r.packs.values())+x.store.packs))
    with gzip.open(a.output/'manifests/objects.jsonl.gz','wb') as f:
        for h,v in r.objects.items():f.write(encoded(v)+b'\n')
        for h,v in x.store.objects.items():
            if h not in r.objects:f.write(encoded(dict(sha256=h,**v))+b'\n')
    catalog=copy.deepcopy(r.catalog)
    for c in catalog['collections']:c['manifest_shards']=streams[c['collection']].finish()
    (a.output/'catalog.json').write_bytes(encoded(catalog));report=dict(converted_record_references=count,removed_resource_byte_references=removed,transformation_shards=audit.finish(),originals_preserved=True)
    (a.output/'reports/embedded-payload-curation.json').write_bytes(encoded(report));print(json.dumps(report))

if __name__=='__main__':main()
