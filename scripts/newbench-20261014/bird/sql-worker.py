import json, sqlite3, sys, time

q = json.loads(sys.argv[1])
result = {'valid': False, 'passed': False}
try:
    c = sqlite3.connect('file:/db.sqlite?mode=ro&immutable=1', uri=True)
    c.enable_load_extension(False)
    c.execute('PRAGMA query_only=ON')
    main_tables = {r[0] for r in c.execute("SELECT name FROM main.sqlite_master WHERE type IN ('table', 'view')")}
    def authorize(action, a, b, db, source):
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_DENY if str(b).lower() in ('load_extension', 'writefile', 'readfile') else sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # SQLite reports a no-column table read for COUNT(*) with db=None.
            # Admit only known main tables in that case; attached/temp reads stay denied.
            main_read = db == 'main' or (db is None and not b and a in main_tables)
            return sqlite3.SQLITE_OK if main_read else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE) else sqlite3.SQLITE_DENY
    c.set_authorizer(authorize)
    def execute(sql):
        start = time.monotonic()
        c.set_progress_handler(lambda: int(time.monotonic() - start > q.get('timeout', 30)), 10000)
        return set(c.execute(sql).fetchall())
    # Gold failures are environment/dataset exceptions, never candidate failures.
    expected = execute(q['gold'])
    result = {'valid': True, 'passed': False, 'errorType': None, 'sqliteVersion': sqlite3.sqlite_version}
    try:
        actual = execute(q['sql'])
        result.update(passed=actual == expected, errorType=None if actual == expected else 'ResultMismatch')
    except sqlite3.Error as e:
        result.update(errorType='QueryTimeout' if str(e) == 'interrupted' else type(e).__name__, message=str(e)[:600])
    c.close()
except Exception as e:
    result.update(valid=False, passed=False, errorType='GoldOrDatabaseError', message=str(e)[:600])
print(json.dumps(result))
