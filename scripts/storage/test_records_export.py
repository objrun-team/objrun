"""Small regression checks; no original archives, network, or paid runs needed."""
import argparse,base64,collections,gzip,hashlib,io,json,os,pathlib,sqlite3,subprocess,sys,tarfile,tempfile,unittest,zipfile
from export_records import Exporter,PackStore,JsonShards,encoded,sha
from records import Records,database_exports,verify

class ExternalRecordLocationTests(unittest.TestCase):
    def test_run_index_does_not_require_external_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'runs').mkdir()
            (root/'runs/example.jsonl').write_text('{"run_scope":"example/1"}\n',encoding='utf-8')
            reader=pathlib.Path(__file__).with_name('records.py')
            result=subprocess.run([sys.executable,'-B',str(reader),'--root',str(root),'--isolated','runs','--bench','example'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'run_scope':'example/1'})

    def test_missing_bodies_explain_external_root_and_cli_overrides_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'runs').mkdir()
            (root/'runs/example.jsonl').write_text('{"run_scope":"example/1"}\n',encoding='utf-8')
            reader=pathlib.Path(__file__).with_name('records.py');env={**os.environ,'OBJRUN_RECORDS_ROOT':str(root)}
            result=subprocess.run([sys.executable,'-B',str(reader),'runs','--bench','example'],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([sys.executable,'-B',str(reader),'--root',str(root),'verify'],capture_output=True,text=True,env={**env,'OBJRUN_RECORDS_ROOT':str(root/'missing')})
            self.assertEqual(result.returncode,2)
            self.assertIn('Record bodies are stored outside',result.stderr)
            self.assertNotIn('Traceback',result.stderr)

class NestedDatabaseTests(unittest.TestCase):
    def test_resource_hash_cannot_discard_another_wal_state(self):
        from export_records import reviewed_resource_match
        from prepare_incremental import export_signature
        source={'format':'sqlite-tables','source_sha256':'main','source_database_sha256':'main','wal_sha256':None,'tables':[]}
        self.assertTrue(reviewed_resource_match(source,{'main':'reviewed dataset'}))
        state={**source,'wal_sha256':'new-state','wal_bytes':32}
        self.assertFalse(reviewed_resource_match(state,{'main':'reviewed dataset'}))
        self.assertNotEqual(export_signature(source),export_signature(state))
        wrapper={'format':'archive-members','source_sha256':'main','members':[source,state],'transformations':{'sqlite_multiple_wal_states':True}}
        self.assertFalse(reviewed_resource_match(wrapper,{'main':'reviewed dataset'}))
        self.assertEqual(len(export_signature(wrapper)[1]),2)
    def test_dictionary_filter_preserves_schema_and_non_corpus_evidence(self):
        from finalize_incremental import WORDNET_DATASET_COLUMNS,exclude_wordnet_tables
        tables=[dict(name=n,columns=WORDNET_DATASET_COLUMNS[n],source_rows=2,exported_rows=2,content={'bytes':10,'sha256':'fixture','parts':[]}) for n in ('words','synsets','senses')]
        evidence=dict(name='grading_events',columns=['seq','result'],source_rows=1,exported_rows=1,content={'bytes':9,'sha256':'result','parts':[]});tables.append(evidence)
        db={'format':'sqlite-tables','tables':tables};removed=exclude_wordnet_tables(db)
        self.assertEqual(len(removed),3);self.assertEqual(db['tables'][-1],evidence);self.assertIn('content',evidence)
        self.assertEqual(tables[0]['source_rows'],2);self.assertTrue(tables[0]['excluded']);self.assertNotIn('content',tables[0])
    def test_single_bench_source_is_not_relabelled_by_a_dependency_name(self):
        from export_records import bench_of
        self.assertEqual(bench_of('fullf-terminal-bench','runs/sanitize/worker/app/eval/gpqa/dataset.zip'),'terminal-bench')
        self.assertEqual(bench_of('fullf-novaeve-formal-20261013','coordinator/sb_languages/attempt/result.json'),'skillsbench')

    def test_weight_resources_are_removed_but_rng_and_transfer_events_remain(self):
        from curate_embedded_payloads import transform
        from export_records import Scrubber
        with tempfile.TemporaryDirectory() as folder:
            blob=base64.b64encode(b'\0'*16).decode();scrub=Scrubber(pathlib.Path(folder));changes=collections.Counter();resources=[]
            raw=encoded({'id':'real-call','arguments':{'state':{'model.embedding.weight':{'dtype':'float32','shape':[4],'data':blob}},'rng_state':{'data':blob},'seed':42}})
            value=json.loads(transform(raw,scrub,'fixture',changes,resources))
            self.assertIn('model-weight-tensor',value['arguments']['state']['model.embedding.weight']['data'])
            self.assertEqual(value['arguments']['rng_state']['data'],blob);self.assertEqual(value['arguments']['seed'],42)
            rows=[{'op':'begin','shape':[2,1]},{'op':'append-f64','id':'matrix','offset':0,'data':blob,'integers':False},{'op':'end','result':{'passed':False}}]
            raw=b''.join(encoded(row)+b'\n' for row in rows);output=transform(raw,scrub,'fixture',changes,resources);restored=[json.loads(line) for line in output.splitlines()]
            self.assertEqual([x['op'] for x in restored],['begin','append-f64','end']);self.assertIn('bulk-numeric-transfer-payload',restored[1]['data'])
            self.assertEqual(restored[2],rows[2]);self.assertEqual(output.count(b'\n'),3)
            nested=encoded({'body':json.dumps({'Authorization':'Bearer\tfixture-token-with-long-body'})})
            restored=json.loads(transform(nested,scrub,'fixture',changes,resources))
            self.assertEqual(json.loads(restored['body'])['Authorization'],'[REDACTED_CREDENTIAL]')
            value['loss']=float('nan');value['arguments']['state']['model.embedding.weight']['data']=blob
            restored=json.loads(transform(json.dumps(value).encode(),scrub,'fixture',changes,resources))
            self.assertNotEqual(restored['loss'],restored['loss']);self.assertIn('RESOURCE_REMOVED',restored['arguments']['state']['model.embedding.weight']['data'])
    def test_embedded_resources_removed_without_losing_textual_tool_evidence(self):
        from curate_embedded_payloads import transform
        from export_records import Scrubber
        with tempfile.TemporaryDirectory(prefix='objrun-embedded-test-') as directory:
            root=pathlib.Path(directory);(root/'objrun').mkdir();(root/'objrun/.env').write_text('API_KEY=fixture-secret-for-record-check\n')
            trace=b'{"response":"failed","tool_output":"fixture-secret-for-record-check"}'
            raw=encoded({'artifacts':[{'path':'repo/.git/objects/pack/source.pack','base64':base64.b64encode(b'PACK\0'+b'\0'*50).decode()},{'path':'actual-error.log','base64':base64.b64encode(trace).decode()}]})
            changes=collections.Counter();resources=[];out=json.loads(transform(raw,Scrubber(root),'fixture',changes,resources))
            self.assertIn('RESOURCE_REMOVED',out['artifacts'][0]['base64']);self.assertEqual(resources[0]['bytes'],55)
            restored=base64.b64decode(out['artifacts'][1]['base64']);self.assertIn(b'failed',restored);self.assertIn(b'[REDACTED_CREDENTIAL]',restored)
            self.assertNotIn(b'fixture-secret-for-record-check',restored)
            for whitespace in ('\t','\r\n',' '):
                sanitized,counts,_=Scrubber(root).text('Bearer'+whitespace+'fixture-token-with-long-body')
                self.assertEqual(sanitized,'[REDACTED_CREDENTIAL]');self.assertEqual(counts['credential_redaction'],1)
            sanitized,counts,_=Scrubber(root).text('\u5bc6\u94a5'+'sk-'+'a'*24+'\u7ed3\u675f')
            self.assertEqual(sanitized,'\u5bc6\u94a5[REDACTED_CREDENTIAL]\u7ed3\u675f')

    def test_same_claimed_hash_cannot_hide_a_reordered_fragment_sequence(self):
        with tempfile.TemporaryDirectory(prefix='objrun-reassembly-test-') as directory:
            root=pathlib.Path(directory).resolve()
            for name in ('packs','manifests'):(root/name).mkdir()
            store=PackStore(root);store.level=1;content=store.put(b'a'*(256*1024)+b'b'*(256*1024),'fixture');store.finish()
            manifest=JsonShards(root,'fixture')
            for i,parts in enumerate((content['parts'],list(reversed(content['parts'])))):
                manifest.write(dict(collection='fixture',path=str(i),format='text',content={**content,'parts':parts}))
            (root/'catalog.json').write_bytes(encoded({'collections':[{'collection':'fixture','manifest_shards':manifest.finish()}]}))
            with self.assertRaises(AssertionError):verify(Records(root))

    def test_wal_before_main_in_nested_and_streamed_archives(self):
        for mode in ('nested-zip','streamed-stdout','snapshot-names'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(prefix='objrun-record-test-') as directory:
                root=pathlib.Path(directory).resolve()
                assert root.is_relative_to(pathlib.Path(tempfile.gettempdir()).resolve())
                (root/'objrun').mkdir();(root/'objrun/.env').write_text('API_KEY=fixture-secret-for-record-check\n',encoding='utf-8')
                source=root/'source.sqlite';con=sqlite3.connect(source)
                con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA wal_autocheckpoint=0')
                con.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,state TEXT,payload TEXT)');con.commit()
                con.executemany('INSERT INTO events VALUES(?,?,?)',[(1,'passed','start'),(2,'failed','fixture-secret-for-record-check'),(3,'aborted','end')]);con.commit()
                main=source.read_bytes();wal=source.with_name('source.sqlite-wal').read_bytes()
                raw=io.BytesIO()
                with tarfile.open(fileobj=raw,mode='w') as tar:
                    suffix='.snapshot' if mode=='snapshot-names' else ''
                    for name,data in [('run.sqlite-wal'+suffix,wal),('run.sqlite'+suffix,main)]:
                        info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
                exporter=Exporter(argparse.Namespace(workspace=root,output=root/'records',work=root/'work',compression_level=1))
                blob=raw.getvalue()
                if mode=='nested-zip':
                    nested=io.BytesIO()
                    with zipfile.ZipFile(nested,'w') as z:z.writestr('attempt.tar.gz',gzip.compress(blob))
                    result=exporter.process_payload(nested.getvalue(),'fixture','bundle.zip','fixture')
                else:result=exporter.stream_archive(io.BytesIO(blob[4096:]),blob[:4096],'fixture','transport.stdout','fixture')
                databases=list(database_exports(result));self.assertEqual(len(databases),1)
                table=databases[0]['tables'][0];self.assertEqual(table['source_rows'],3)
                self.assertEqual(databases[0]['wal_sha256'],hashlib.sha256(wal).hexdigest())
                self.assertEqual(source.read_bytes(),main);self.assertEqual(source.with_name('source.sqlite-wal').read_bytes(),wal)
                manifest=JsonShards(root/'records','fixture');manifest.write(dict(collection='fixture',path='bundle',bench='fixture',run_scope='fixture',**result))
                (root/'records/catalog.json').write_bytes(encoded(dict(collections=[dict(collection='fixture',manifest_shards=manifest.finish())])))
                exporter.store.finish();reader=Records(root/'records');proof=verify(reader)
                self.assertEqual(proof['database_rows'],3)
                restored=b''.join(reader.parts(table['content']));rows=[json.loads(line) for line in restored.splitlines()]
                self.assertEqual([r['values'][0] for r in rows],[1,2,3])
                self.assertNotIn(b'fixture-secret-for-record-check',restored)
                self.assertIn(b'[REDACTED_CREDENTIAL]',restored)
                command=[sys.executable,'-B',str(pathlib.Path(__file__).with_name('records.py')),'--root',str(root/'records'),'--isolated','read','--collection','fixture','--path','bundle']
                if mode=='nested-zip':command+=['--member','attempt.tar.gz']
                command+=['--member','run.sqlite'+suffix,'--table','events']
                self.assertEqual(subprocess.check_output(command),restored)
                con.close()

    def test_append_preserves_old_packs_and_reuses_shared_content(self):
        with tempfile.TemporaryDirectory(prefix='objrun-append-test-') as directory:
            root=pathlib.Path(directory).resolve()
            assert root.is_relative_to(pathlib.Path(tempfile.gettempdir()).resolve())
            def make(name,values):
                folder=root/name
                for child in ('packs','manifests','reports','runs','summaries'):(folder/child).mkdir(parents=True)
                store=PackStore(folder);store.level=1;manifest=JsonShards(folder,name)
                for i,data in enumerate(values):
                    manifest.write(dict(collection=name,path=str(i),bench='fixture',run_scope=name,format='text',source_bytes=len(data),source_sha256=sha(data),content=store.put(data,'fixture')))
                store.finish();collection=dict(collection=name,manifest_shards=manifest.finish(),by_bench={'fixture':{'discovered_files':len(values)}})
                catalog=dict(collections=[collection],benches={'fixture':{'retained_files':len(values)}},formats={'text':len(values)},deferred_original_collections=['new'],errors=[])
                (folder/'catalog.json').write_bytes(encoded(catalog));return folder
            base=make('base',[b'shared']);additional=make('new',[b'shared',b'new record'])
            override=json.dumps(['base','0'],separators=(',',':'))
            (additional/'reports/incremental-preparation.json').write_bytes(encoded({'entry_overrides':{override:['new','0']}}))
            before=(base/'packs/part-00000.tar.zst').read_bytes();out=root/'combined'
            subprocess.check_output([sys.executable,'-B',str(pathlib.Path(__file__).with_name('append_records.py')),'--base',str(base),'--supplement',str(additional),'--output',str(out),'--label','addition'])
            self.assertEqual((out/'packs/part-00000.tar.zst').read_bytes(),before)
            self.assertEqual((base/'packs/part-00000.tar.zst').read_bytes(),before)
            reader=Records(out);proof=verify(reader)
            self.assertEqual(proof['objects'],2);self.assertEqual(len(list(reader.entries())),2)
            self.assertEqual(reader.get('base','0')['collection'],'new')
            self.assertEqual(b''.join(reader.parts(reader.get('base','0')['content'])),b'shared')
            self.assertEqual(b''.join(reader.parts(reader.get('new','1')['content'])),b'new record')
            rules=root/'rules.json';rules.write_text(json.dumps([dict(id='fixture-resource',collection='new',pattern='^1$',reason='Reviewed synthetic resource',evidence='Test fixture')]))
            curated=root/'curated'
            subprocess.check_output([sys.executable,'-B',str(pathlib.Path(__file__).with_name('finalize_incremental.py')),'--base',str(base),'--source',str(out),'--output',str(curated),'--rules',str(rules)])
            final=Records(curated);self.assertEqual(verify(final)['objects'],1)
            self.assertEqual(b''.join(final.parts(final.get('base','0')['content'])),b'shared')
            self.assertEqual((curated/'packs/part-00000.tar.zst').read_bytes(),before)
            proof=json.loads((curated/'reports/incremental-finalization.json').read_text())
            self.assertEqual(proof['resource_exclusion_counts']['fixture-resource'],1)
            subprocess.check_output([sys.executable,'-B',str(pathlib.Path(__file__).with_name('shard_object_index.py')),'--root',str(curated)])
            indexed=Records(curated);self.assertEqual(indexed.objects,final.objects)
            self.assertEqual(verify(indexed)['objects'],1)

    def test_truncated_transport_preserves_available_text_and_marks_gap(self):
        with tempfile.TemporaryDirectory(prefix='objrun-recovery-test-') as directory:
            root=pathlib.Path(directory).resolve();source=root/'source'
            for name in ('packs','manifests','reports','runs','summaries'):(source/name).mkdir(parents=True)
            header=tarfile.TarInfo('actual-error.log');header.size=10000
            raw=header.tobuf()+b'Tool failed: available original diagnostic\n'
            store=PackStore(source);content=store.put(raw,'fixture');store.finish()
            manifest=JsonShards(source,'fixture');manifest.write(dict(collection='fixture',bench='fixture',run_scope='run',path='transport.stdout',source_sha256=sha(raw),source_bytes=len(raw),format='archive-review-required',pending='ReadError',content=content))
            (source/'catalog.json').write_bytes(encoded({'collections':[{'collection':'fixture','manifest_shards':manifest.finish()}]}))
            out=root/'recovered';originals=root/'originals';originals.mkdir()
            subprocess.check_output([sys.executable,'-B',str(pathlib.Path(__file__).with_name('recover_tar_records.py')),'--source',str(source),'--output',str(out),'--work',str(root/'work'),'--workspace',str(root),'--originals',str(originals)])
            reader=Records(out);entry=reader.get('fixture','transport.stdout');member=entry['members'][0]
            self.assertEqual(b''.join(reader.parts(member['content'])),raw[512:])
            self.assertFalse(member['source_truncation']['complete'])
            self.assertEqual(member['source_truncation']['declared_bytes'],10000)
            self.assertFalse(entry['source_transport_recovery']['source_complete'])
            self.assertEqual(json.loads(encoded({'path':'invalid-\udcff-name'}))['path'],'invalid-\udcff-name')

if __name__=='__main__':unittest.main()
