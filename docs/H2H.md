# H2H

The application's state component consists of a SQLite database and a Fastify API. The database lives in `data/` at the repository root.

**All configuration lives in the root `config.yaml`.** It defines the port, database file, PRAGMAs, token, write permissions, and row limits. There is no second set of editable defaults in the code. Paths resolve relative to the directory containing `config.yaml`, rather than the process working directory.

This document covers the API and its two enforcement boundaries. See the root `README.md` for startup and build instructions.

## API

The prefix comes from `api.prefix` (default: `/api`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness, database location, and write status. **No token check**, so health probes can access it |
| GET | `/tables` | All tables and views, with row counts |
| GET | `/tables/:table/schema` | Columns, indexes, and table creation statements |
| GET | `/tables/:table/rows` | Read rows. `?limit&offset&order&dir` |
| POST | `/query` | Query with `{sql, params}` through a **read-only connection** |
| POST | `/exec` | Write with `{sql, params}`. Requires `api.allowWrite` |
| POST | `/tables/:table/rows` | Insert one row supplied as the request body. Requires `api.allowWrite` |

An array in `params` binds values by position (`?`); an object binds them by name (`:name`).

```
curl 127.0.0.1:7801/api/health
curl -X POST 127.0.0.1:7801/api/query -H 'content-type: application/json' \
  --data-binary '{"sql":"select * from note where body = :b","params":{"b":"second"}}'
```

## Two enforcement boundaries

**Read-only access is enforced by the connection.** `/query` uses a `readOnly: true` connection. SQLite rejects writes with `attempt to write a readonly database`. The implementation does not try to recognize SQL keywords such as `update`: a keyword list cannot cover every write, and one missed case would permit a real write.

**Table and column names are checked against the database first.** Identifiers cannot be bound through placeholders, so every name is checked through `sqlite_master` or `table_info` before being interpolated into SQL. Unknown names produce a 404 or 400 response.

## Token

An empty `api.token` disables authentication (the local default). To enable it, set the field to `${H2H_TOKEN}`, put the value in the root `.env` file (excluded from version control), and send `Authorization: Bearer <token>` from the client. Any configuration value can use `${VAR}` to read an environment variable.
