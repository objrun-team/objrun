"""Small regression checks; no original archives, network, or paid runs needed."""
import argparse,gzip,hashlib,io,json,pathlib,sqlite3,subprocess,sys,tarfile,tempfile,unittest,zipfile
from export_records import Exporter,PackStore,JsonShards,encoded,sha
from records import Records,database_exports,verify

class NestedDatabaseTests(unittest.TestCase):
    def test_wal_before_main_in_nested_and_streamed_archives(self):
        for mode in ('nested-zip','streamed-stdout'):
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
                    for name,data in [('run.sqlite-wal',wal),('run.sqlite',main)]:
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
                command+=['--member','run.sqlite','--table','events']
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
            before=(base/'packs/part-00000.tar.zst').read_bytes();out=root/'combined'
            subprocess.check_output([sys.executable,'-B',str(pathlib.Path(__file__).with_name('append_records.py')),'--base',str(base),'--supplement',str(additional),'--output',str(out),'--label','addition'])
            self.assertEqual((out/'packs/part-00000.tar.zst').read_bytes(),before)
            self.assertEqual((base/'packs/part-00000.tar.zst').read_bytes(),before)
            reader=Records(out);proof=verify(reader)
            self.assertEqual(proof['objects'],2);self.assertEqual(len(list(reader.entries())),3)
            self.assertEqual(b''.join(reader.parts(reader.get('new','1')['content'])),b'new record')

if __name__=='__main__':unittest.main()
