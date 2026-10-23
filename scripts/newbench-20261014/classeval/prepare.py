import hashlib, json, pathlib
root = pathlib.Path(__file__).resolve().parent
rows = json.loads((root / 'upstream/data/ClassEval_data.json').read_text(encoding='utf8'))
old = json.loads((root / 'public-tasks.json').read_text(encoding='utf8'))
assert len(rows) == len(old) == 100
changes = []
public = []
for row, prior in zip(rows, old):
    assert row['task_id'] == prior['officialId']
    missing = [i for i in row['import_statement'] if i not in row['skeleton']]
    skeleton = '\n'.join(missing) + ('\n\n' if missing else '') + row['skeleton']
    prompt = 'Implement the complete Python class described below. Preserve its interface and implement every method. Return the complete Python code.\n\n' + skeleton
    public.append({'officialId': row['task_id'], 'class_name': row['class_name'], 'import_statement': row['import_statement'], 'prompt': prompt, 'promptSha256': hashlib.sha256(prompt.encode()).hexdigest()})
    if missing: changes.append({'taskId': row['task_id'], 'addedImports': missing})
(root / 'public-tasks.json').write_text(json.dumps(public, indent=2, ensure_ascii=False)+'\n', encoding='utf8')
(root / 'catalog-audit.json').write_text(json.dumps({'count':100,'sourceCommit':'90825141e640418ae6dc8257397345ee3ac36cbc','sourceVersion':'v1.0.0','addedImports':changes,'privateFieldsExcluded':['test','solution_code','test_classes'],'publicCatalogSha256':hashlib.sha256((root/'public-tasks.json').read_bytes()).hexdigest()},indent=2)+'\n',encoding='utf8')
print(json.dumps({'count':100,'addedImports':changes}))
