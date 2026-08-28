# H2H

程序的状态部件：一个 SQLite 库 + 用 Fastify 开出来的接口。库落在仓库根的 `data/`。

**配置只有一处：仓库根的 `config.yaml`。** 端口、库文件、PRAGMA、令牌、能不能写、
一次最多几行，全在那儿；代码里不留第二处默认值可改。路径一律相对
`config.yaml` 所在的目录，不是相对 cwd。

这一份只讲接口和它的两条边界。怎么跑、怎么打包在根 `README.md`。

## 接口

前缀来自 `api.prefix`（默认 `/api`）。

| 方法 | 路径 | 干什么 |
| --- | --- | --- |
| GET | `/health` | 活着没、库在哪、写开没开。**不校验令牌**，好让探活能打 |
| GET | `/tables` | 所有表和视图，带行数 |
| GET | `/tables/:table/schema` | 列、索引、建表语句 |
| GET | `/tables/:table/rows` | 读行。`?limit&offset&order&dir` |
| POST | `/query` | `{sql, params}` 查。走**只读连接** |
| POST | `/exec` | `{sql, params}` 写。要 `api.allowWrite` |
| POST | `/tables/:table/rows` | 插一行，请求体就是那一行。要 `api.allowWrite` |

`params` 是数组就按位置绑（`?`），是对象就按名字绑（`:name`）。

```
curl 127.0.0.1:7801/api/health
curl -X POST 127.0.0.1:7801/api/query -H 'content-type: application/json' \
  --data-binary '{"sql":"select * from note where body = :b","params":{"b":"second"}}'
```

## 两条边界

**只读是连接层面的。** `/query` 走一条 `readOnly: true` 的连接，写进去
直接被 SQLite 挡成 `attempt to write a readonly database` —— 不是靠认
SQL 里有没有 `update` 那种关键字，那种判法永远数不全，漏一次就是真写进去。

**表名和列名都先对着库核过。** 它们没法用占位符绑，所以拼进 SQL 之前
一律去 `sqlite_master` / `table_info` 查一遍，对不上就 404 / 400。

## 令牌

`api.token` 留空 = 不校验（本地默认）。要校验就写 `${H2H_TOKEN}`，值放进
仓库根的 `.env`（那个文件不进版本库），客户端发 `Authorization: Bearer <token>`。
配置里任何值都能写 `${VAR}` 从环境变量取。
