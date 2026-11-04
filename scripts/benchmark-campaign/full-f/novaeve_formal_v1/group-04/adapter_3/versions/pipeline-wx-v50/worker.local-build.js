// @bun
var __esm = (fn, res) => () => (fn && (res = fn(fn = 0)), res);
var __promiseAll = (args) => Promise.all(args);

// scripts/benchmark-repair/paid-resource-proof-v2.ts
import { createHash } from "crypto";
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, realpathSync, statSync } from "fs";
import { isAbsolute, join, relative, resolve } from "path";
import { gunzipSync } from "zlib";
function demand(value, code) {
  if (!value)
    throw new ResourceAdmissionError(code);
}
function ordinaryDirectory(path) {
  const p = resolve(path);
  mkdirSync(p, { recursive: true });
  demand(lstatSync(p).isDirectory() && !lstatSync(p).isSymbolicLink() && realpathSync(p) === p, "ordinary_directory_required");
  return p;
}
function fileHash(path) {
  const before = statSync(path), fd = openSync(path, "r"), digest = createHash("sha256"), buffer = Buffer.alloc(65536);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync(fd);
  }
  const after = statSync(path);
  demand(before.size === after.size && before.mtimeMs === after.mtimeMs, "file_changed_during_hash");
  return digest.digest("hex");
}
function verifyPin(pin, base, maxBytes = 128 * 1024 ** 2) {
  demand(pin && typeof pin.path === "string" && /^[a-f0-9]{64}$/.test(pin.sha256), "invalid_pin");
  const path = isAbsolute(pin.path) ? resolve(pin.path) : resolve(base ?? ".", pin.path);
  demand(lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink(), "pin_not_regular");
  const size = statSync(path).size;
  demand(size <= maxBytes && (pin.bytes === undefined || pin.bytes === size) && fileHash(path) === pin.sha256, "pin_changed");
  return path;
}
function actualPin(path) {
  return { path: resolve(path), bytes: statSync(path).size, sha256: fileHash(path) };
}
function jsonPin(pin, base) {
  return JSON.parse(readFileSync(verifyPin(pin, base), "utf8"));
}
function integer(n) {
  return typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
}
function requestValues(raw) {
  demand(raw.byteLength > 0 && raw.byteLength <= 4 * 1024 ** 2, "request_size");
  const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  demand(data.model === "deepseek-flash" && data.stream !== true && Array.isArray(data.messages), "request_profile");
  const { max_tokens: a, max_completion_tokens: b } = data;
  demand((a === undefined || integer(a)) && (b === undefined || integer(b)) && (a === undefined || b === undefined || a === b), "output_limit");
  const output = a ?? b;
  demand(integer(output) && output > 0 && output <= 16384, "output_limit");
  const upper = raw.byteLength + 2048 + data.messages.length * 256;
  demand(integer(upper), "input_bound");
  return { data, inputUpper: upper, output, peakNano: BigInt(upper) * 2000n + BigInt(output) * 8000n };
}
function gzipProof(pin, rawSha, base, maxRaw = 64 * 1024 ** 2) {
  const path = verifyPin(pin, base, 65 * 1024 ** 2), before = statSync(path), raw = gunzipSync(readFileSync(path), { maxOutputLength: maxRaw });
  demand(hash(raw) === rawSha && statSync(path).mtimeMs === before.mtimeMs && statSync(path).size === before.size, "raw_digest_changed");
  return raw;
}
function validatePrices(pin, base) {
  const p = jsonPin(pin, base);
  demand(p.protocol === "deepseek-cny-pricing-source-snapshot-v1" && p.currency === "CNY" && p.model === "deepseek-flash" && p.modelCalls === 0, "price_profile");
  demand(p.officialSource === "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/" && same(p.peak, { uncachedInput: 2, cachedInput: 0.04, output: 8 }) && same(p.offPeak, { uncachedInput: 1, cachedInput: 0.02, output: 4 }), "price_rates");
  return p;
}
function peakWindow(start, end) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start)
    return { peak: true, clockFault: true };
  if (end - start > 32 * 86400000)
    return { peak: true, clockFault: false };
  const shifted = start + 8 * 3600000, last = end + 8 * 3600000;
  let day = Math.floor(shifted / 86400000) * 86400000;
  for (;day <= last; day += 86400000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday === 0 || weekday === 6)
      continue;
    for (const [s, e] of [[9, 12], [14, 18]])
      if (last >= day + s * 3600000 && shifted <= day + e * 3600000)
        return { peak: true, clockFault: false };
  }
  return { peak: false, clockFault: false };
}
function pricedUsage(usage, peak) {
  demand(usage && integer(usage.prompt_tokens) && integer(usage.completion_tokens), "usage_missing_or_invalid");
  const hit = usage.prompt_cache_hit_tokens ?? 0;
  demand(integer(hit) && hit <= usage.prompt_tokens, "cache_usage_invalid");
  if (usage.prompt_cache_miss_tokens !== undefined)
    demand(integer(usage.prompt_cache_miss_tokens) && usage.prompt_cache_miss_tokens + hit === usage.prompt_tokens, "cache_usage_invalid");
  const miss = usage.prompt_tokens - hit;
  return BigInt(miss) * (peak ? 2000n : 1000n) + BigInt(hit) * (peak ? 40n : 20n) + BigInt(usage.completion_tokens) * (peak ? 8000n : 4000n);
}

class JournalBinding {
  directory;
  configPin;
  sourcePin;
  config;
  configPath;
  path;
  configSha;
  prefix;
  checkpoints = new Map;
  starts = new Map;
  finishes = new Map;
  constructor(directory, configPin, sourcePin) {
    this.directory = directory;
    this.configPin = configPin;
    this.sourcePin = sourcePin;
    demand(sourcePin.sha256 === JOURNAL_SOURCE_SHA, "journal_source_version");
    verifyPin(sourcePin);
    this.configPath = verifyPin(configPin);
    demand(resolve(this.configPath) === join(resolve(directory), "journal-config.json"), "journal_config_path");
    this.config = JSON.parse(readFileSync(this.configPath, "utf8"));
    demand(this.config.protocol === "campaign-api-journal-v1" && this.config.pendingLimit === 4 && this.config.model === "deepseek-flash", "journal_config_profile");
    this.configSha = configPin.sha256;
    this.path = join(resolve(directory), "api-events.jsonl");
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha };
    this.checkpoints.set(0, this.prefix);
  }
  consume(target) {
    demand(integer(target.bytes) && integer(target.eventCount) && /^[a-f0-9]{64}$/.test(target.lastSha256), "invalid_journal_prefix");
    if (target.bytes <= this.prefix.bytes) {
      demand(same(this.checkpoints.get(target.bytes), target), "unknown_historical_prefix");
      return;
    }
    demand(existsSync(this.path) && statSync(this.path).size >= target.bytes, "journal_prefix_missing");
    const fd = openSync(this.path, "r");
    let at = this.prefix.bytes, carry = Buffer.alloc(0);
    try {
      while (at < target.bytes) {
        const b = Buffer.alloc(Math.min(16384, target.bytes - at));
        const n = readSync(fd, b, 0, b.length, at);
        demand(n > 0, "journal_short_read");
        at += n;
        carry = Buffer.concat([carry, b.subarray(0, n)]);
        let nl;
        while ((nl = carry.indexOf(10)) >= 0) {
          const line = carry.subarray(0, nl + 1);
          demand(line.length <= 65536, "journal_line_limit");
          const frame = JSON.parse(line.subarray(0, -1).toString("utf8"));
          demand(Buffer.from(JSON.stringify(frame) + `
`).equals(line) && frame.protocol === "campaign-api-journal-v1" && frame.eventSeq === this.prefix.eventCount && frame.previousEventSha256 === this.prefix.lastSha256 && integer(frame.requestSeq), "journal_chain");
          const offset = this.prefix.bytes, end = offset + line.length, sha = hash(line);
          if (frame.kind === "start") {
            demand(!this.starts.has(frame.requestSeq), "duplicate_start");
            this.starts.set(frame.requestSeq, frame);
          } else if (frame.kind === "finish") {
            demand(this.starts.has(frame.requestSeq) && !this.finishes.has(frame.requestSeq), "duplicate_or_unknown_finish");
            this.finishes.set(frame.requestSeq, { frame, offset, end, sha });
          } else
            demand(false, "journal_kind");
          this.prefix = { bytes: end, eventCount: this.prefix.eventCount + 1, lastSha256: sha };
          this.checkpoints.set(end, this.prefix);
          carry = carry.subarray(nl + 1);
        }
        demand(carry.length <= 65536, "journal_line_limit");
      }
    } finally {
      closeSync(fd);
    }
    demand(carry.length === 0 && same(this.prefix, target), "journal_prefix_mismatch");
  }
  start(seq, prefix) {
    this.consume(prefix);
    const frame = this.starts.get(seq);
    demand(frame && frame.eventSeq === prefix.eventCount - 1, "not_this_start_prefix");
    return frame.record;
  }
  finish(seq, ref) {
    demand(integer(ref.finishOffset) && integer(ref.finishEnd) && ref.finishEnd > ref.finishOffset && ref.finishEnd - ref.finishOffset <= 65536, "finish_offset");
    const fd = openSync(this.path, "r"), line = Buffer.alloc(ref.finishEnd - ref.finishOffset);
    try {
      demand(readSync(fd, line, 0, line.length, ref.finishOffset) === line.length, "finish_short_read");
    } finally {
      closeSync(fd);
    }
    demand(hash(line) === ref.finishLineSha256 && line.at(-1) === 10, "finish_digest");
    const f = JSON.parse(line.subarray(0, -1).toString("utf8"));
    demand(f.kind === "finish" && f.requestSeq === seq, "finish_sequence");
    this.consume({ bytes: ref.finishEnd, eventCount: f.eventSeq + 1, lastSha256: ref.finishLineSha256 });
    const known = this.finishes.get(seq);
    demand(known && known.offset === ref.finishOffset && known.end === ref.finishEnd && known.sha === ref.finishLineSha256, "finish_chain_membership");
    return known.frame.record;
  }
  current() {
    return { ...this.prefix };
  }
}
var REAL_CLOCK, JOURNAL_SOURCE_SHA, ResourceAdmissionError, hash = (b) => createHash("sha256").update(b).digest("hex"), same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var init_paid_resource_proof_v2 = __esm(() => {
  REAL_CLOCK = Object.freeze({ wallUnixMs: () => Date.now(), monotonicNs: () => process.hrtime.bigint() });
  JOURNAL_SOURCE_SHA = createHash("sha256").update(readFileSync(new URL("./campaign-journal.ts", import.meta.url))).digest("hex");
  ResourceAdmissionError = class ResourceAdmissionError extends Error {
    code;
    constructor(code) {
      super(code);
      this.code = code;
      this.name = "ResourceAdmissionError";
    }
  };
});

// app/src/H2H/db.ts
function all(db, sql, params) {
  return db.all(sql, params);
}
function run(db, sql, params) {
  return db.run(sql, params);
}
var init_db = () => {};

// app/src/engine/plugin.ts
import { statSync as statSync2 } from "fs";
import { resolve as resolve3 } from "path";
import { fileURLToPath, pathToFileURL } from "url";
function hostPath() {
  const given = process.env.TGENGIN_PLUGIN_HOST;
  if (given && given.trim())
    return given;
  try {
    const beside = fileURLToPath(new URL("./plugin-host.ts", import.meta.url));
    if (statSync2(beside).isFile())
      return beside;
  } catch {}
  return "./engine/plugin-host.ts";
}

class Live {
  stamp;
  #w;
  #ready;
  #id = 0;
  #waiting = new Map;
  #dead = null;
  constructor(name, spec, stamp) {
    this.stamp = stamp;
    this.#w = new Worker(HOST);
    this.#ready = new Promise((ok, fail) => {
      const wall = setTimeout(() => fail(new Error(`${name}: the worker did not come up within ${READY_MS}ms (${HOST})`)), READY_MS);
      const up = () => {
        clearTimeout(wall);
        ok();
      };
      const no = (e) => {
        clearTimeout(wall);
        this.#die(e);
        fail(e);
      };
      this.#w.onmessage = (e) => {
        const m = e.data ?? {};
        if (m.kind === "ready")
          return up();
        if (m.kind === "failed")
          return no(new Error(`${name}: ${m.error}`));
        if (m.kind !== "done")
          return;
        const w = this.#waiting.get(Number(m.id));
        if (!w)
          return;
        this.#waiting.delete(Number(m.id));
        if (m.ok)
          w.ok(m.value);
        else
          w.fail(new Error(String(m.error)));
      };
      this.#w.onerror = (e) => no(new Error(`${name}: ${e.message}`));
    });
    this.#ready.catch(() => {});
    this.#w.postMessage({ kind: "load", module: spec });
  }
  #die(e) {
    this.#dead ??= e;
    for (const w of this.#waiting.values())
      w.fail(e);
    this.#waiting.clear();
  }
  async call(exp, arg) {
    await this.#ready;
    if (this.#dead)
      throw this.#dead;
    const id = ++this.#id;
    return await new Promise((ok, fail) => {
      this.#waiting.set(id, { ok, fail });
      this.#w.postMessage({ kind: "call", id, export: exp, arg });
    });
  }
  close() {
    this.#dead ??= new Error("already closed");
    this.#w.terminate();
  }
}

class Plugins {
  #live = new Map;
  #on = new Map;
  host = HOST;
  async probe() {
    const w = new Worker(HOST);
    try {
      await new Promise((ok, fail) => {
        const wall = setTimeout(() => fail(new Error(`did not come up within ${READY_MS}ms`)), READY_MS);
        w.onmessage = () => {
          clearTimeout(wall);
          ok();
        };
        w.onerror = (e) => {
          clearTimeout(wall);
          fail(new Error(e.message));
        };
        w.postMessage({ kind: "load", module: "file:///tgengin-probe-not-a-real-module" });
      });
      return null;
    } catch (e) {
      return `plugin path unusable (${HOST}): ${e instanceof Error ? e.message : String(e)} - point TGENGIN_PLUGIN_HOST at plugin-host.ts`;
    } finally {
      w.terminate();
    }
  }
  async call(name, spec, arg) {
    const hash2 = spec.lastIndexOf("#");
    const path = resolve3(hash2 === -1 ? spec : spec.slice(0, hash2));
    const exp = hash2 === -1 ? "default" : spec.slice(hash2 + 1);
    let stamp = 0;
    try {
      stamp = statSync2(path).mtimeMs;
    } catch {
      throw new Error(`${name}: cannot find ${path}`);
    }
    this.#on.set(name, path);
    const had = this.#live.get(path);
    if (!had || had.stamp !== stamp) {
      had?.close();
      this.#live.set(path, new Live(name, pathToFileURL(path).href, stamp));
    }
    return await this.#live.get(path).call(exp, arg);
  }
  drop(name) {
    const path = this.#on.get(name);
    if (path === undefined)
      return false;
    this.#on.delete(name);
    if ([...this.#on.values()].includes(path))
      return false;
    this.#live.get(path)?.close();
    this.#live.delete(path);
    return true;
  }
  names() {
    return [...this.#live.keys()].sort();
  }
  closeAll() {
    for (const l of this.#live.values())
      l.close();
    this.#live.clear();
    this.#on.clear();
  }
}
var HOST, READY_MS = 1e4;
var init_plugin = __esm(() => {
  HOST = hostPath();
});

// app/src/engine/registry.ts
class Registry {
  #by = new Map;
  plugins = new Plugins;
  beforeSync = null;
  register(db, name, expectMs, fn) {
    if (!IN.test(name))
      throw new Error(`an in-process handle name must start with fn: - got ${name}`);
    if (!Number.isFinite(expectMs) || expectMs <= 0)
      throw new Error(`expect_ms for ${name} must be a positive number`);
    this.#by.set(name, { name, expectMs, call: fn, where: "in" });
    run(db, `insert into handle (name, expect_ms, module) values (?, ?, null)
             on conflict(name) do update set expect_ms = excluded.expect_ms`, [name, expectMs]);
  }
  adopt(name, expectMs, fn) {
    this.#by.set(name, { name, expectMs, call: fn, where: "out" });
  }
  sync(db) {
    this.beforeSync?.();
    const rows = all(db, `select name, expect_ms, module from handle`);
    const added = [];
    const missing = [];
    for (const r of rows) {
      if (this.#by.has(r.name)) {
        this.#by.get(r.name).expectMs = r.expect_ms;
        continue;
      }
      if (OUT.test(r.name)) {
        this.#by.set(r.name, { name: r.name, expectMs: r.expect_ms, where: "out", call: remote(r.name) });
        added.push(r.name);
      } else if (IN.test(r.name) && r.module) {
        const spec = r.module;
        this.#by.set(r.name, {
          name: r.name,
          expectMs: r.expect_ms,
          where: "in",
          plugin: spec,
          call: (arg) => this.plugins.call(r.name, spec, arg)
        });
        added.push(r.name);
      } else {
        missing.push(r.name);
      }
    }
    const inDb = new Set(rows.map((r) => r.name));
    const dropped = [];
    for (const [name, e] of this.#by) {
      if (e.plugin === undefined || inDb.has(name))
        continue;
      this.plugins.drop(name);
      this.#by.delete(name);
      dropped.push(name);
    }
    if (missing.length) {
      throw new Error(`registered in the database but never registered in this process: ${missing.join(", ")}`);
    }
    return { added, missing, dropped };
  }
  get(name) {
    const e = this.#by.get(name);
    if (!e)
      throw new Error(`no such handle: ${name}`);
    return e;
  }
  has(name) {
    return this.#by.has(name);
  }
  names() {
    return [...this.#by.keys()].sort();
  }
}
async function graderFetch(url, init) {
  const token = process.env.TGENGIN_GRADER_TOKEN;
  if (!token)
    return fetch(url, init);
  const raw = process.env.TGENGIN_GRADER_ORIGINS?.trim();
  if (!raw)
    throw new Error("TGENGIN_GRADER_ORIGINS is required when TGENGIN_GRADER_TOKEN is configured");
  let entries;
  try {
    entries = raw.startsWith("[") ? JSON.parse(raw) : raw.split(",");
  } catch {
    throw new Error("TGENGIN_GRADER_ORIGINS must be a list of URL origins");
  }
  if (!Array.isArray(entries) || entries.length === 0)
    throw new Error("TGENGIN_GRADER_ORIGINS must be a nonempty list of URL origins");
  const origins = new Set(entries.map((entry) => {
    try {
      const parsed = new URL(String(entry).trim());
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash)
        throw new Error;
      return parsed.origin;
    } catch {
      throw new Error("TGENGIN_GRADER_ORIGINS contains an invalid URL origin");
    }
  }));
  const headers = new Headers(init.headers);
  headers.delete("X-ObjRun-Grader-Token");
  const trusted = origins.has(new URL(url).origin);
  if (trusted)
    headers.set("X-ObjRun-Grader-Token", token);
  return fetch(url, { ...init, headers, ...trusted ? { redirect: "error" } : {} });
}
function remote(url) {
  return async (arg) => {
    const res = await graderFetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(arg ?? {})
    });
    if (!res.ok)
      throw Object.assign(new Error(`${url} returned ${res.status}`), { statusCode: res.status });
    return await res.json();
  };
}
var IN, OUT;
var init_registry = __esm(() => {
  init_db();
  init_plugin();
  IN = /^fn:/;
  OUT = /^https?:\/\//;
});

// app/src/objective/spec.ts
function domainText(d) {
  return d.kind === "bool" ? "bool" : `bool[${d.width}]`;
}
function parseDomain(text) {
  if (text !== null && typeof text === "object") {
    const d = text;
    if (d.kind === "bool")
      return BOOL;
    if (d.kind === "bool[]" && Number.isInteger(d.width) && Number(d.width) >= 1) {
      return { kind: "bool[]", width: Number(d.width) };
    }
    throw new Error(`unrecognised domain: ${JSON.stringify(text)}`);
  }
  const s = String(text ?? "").trim();
  if (s === "bool")
    return BOOL;
  const m = /^bool\[(\d+)\]$/.exec(s);
  if (m) {
    const n = Number(m[1]);
    if (!Number.isInteger(n) || n < 1)
      throw new Error(`the n in bool[n] must be an integer >= 1, got ${m[1]}`);
    return { kind: "bool[]", width: n };
  }
  throw new Error(`domain must be 'bool' or 'bool[n]', got ${JSON.stringify(text)}. The domain set is closed; custom domains are not accepted`);
}
function checkValue(d, v) {
  if (d.kind === "bool") {
    return typeof v === "boolean" ? null : `domain ${domainText(d)} expects a bool, got ${typeof v}`;
  }
  if (!Array.isArray(v))
    return `domain ${domainText(d)} expects a list of bools, got ${typeof v}`;
  if (v.length !== d.width)
    return `domain ${domainText(d)} expects length ${d.width}, got ${v.length}`;
  const bad = v.map((x, i) => typeof x === "boolean" ? -1 : i).filter((i) => i >= 0);
  if (bad.length)
    return `domain ${domainText(d)} expects every element to be a bool; indices ${bad.slice(0, 5).join(",")} are not`;
  return null;
}
function parseObjective(raw) {
  if (raw === null || typeof raw !== "object")
    throw new Error("the grading function must be an object");
  const o = raw;
  if (!Array.isArray(o.nodes))
    throw new Error("the grading function needs nodes, and it must be an array");
  if (!Array.isArray(o.edges))
    throw new Error("the grading function needs edges, and it must be an array");
  const nodes = o.nodes.map((n, i) => {
    if (n === null || typeof n !== "object")
      throw new Error(`node ${i} is not an object`);
    const x = n;
    if (typeof x.name !== "string" || !x.name.trim())
      throw new Error(`node ${i} has no name`);
    return {
      name: x.name,
      moment: String(x.moment ?? ""),
      domain: parseDomain(x.domain),
      handle: String(x.handle ?? "")
    };
  });
  const edges = o.edges.map((e, i) => {
    if (e === null || typeof e !== "object")
      throw new Error(`edge ${i} is not an object`);
    const x = e;
    return { src: String(x.src ?? ""), out: Number(x.out ?? 0), dst: String(x.dst ?? "") };
  });
  const asked = Number(o.checks);
  if (o.reuse !== undefined && o.reuse !== "text" && o.reuse !== "never")
    throw new Error("objective.reuse must be 'text' or 'never'");
  return { nodes, edges, sink: String(o.sink ?? ""), checks: Number.isFinite(asked) && asked > 0 ? asked : 5, reuse: o.reuse === "text" ? "text" : "never" };
}
var BOOL;
var init_spec = __esm(() => {
  BOOL = { kind: "bool", width: 1 };
});

// app/src/objective/run.ts
function unwrap(got) {
  if (got !== null && typeof got === "object" && !Array.isArray(got)) {
    const status = got;
    if (status.valid === false || status.outcome === "grader_error")
      throw new Error("grader returned an invalid decision");
  }
  if (got !== null && typeof got === "object" && !Array.isArray(got) && "value" in got) {
    const o = got;
    return { value: o.value, note: say(o.note) };
  }
  return { value: got, note: "" };
}
function candidateInput(task, body, chain = []) {
  return { task: { ...task, result: body }, chain, result: { kind: "prompt", body } };
}
function say(note) {
  if (note === undefined || note === null)
    return "";
  if (typeof note === "string")
    return note;
  try {
    return JSON.stringify(note);
  } catch {
    return String(note);
  }
}
function topo(o) {
  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  const deg = o.nodes.map(() => 0);
  for (const e of o.edges)
    deg[idx.get(e.dst)]++;
  const out = [];
  const stack = o.nodes.filter((_, i) => deg[i] === 0).map((n) => n.name);
  while (stack.length) {
    const name = stack.pop();
    out.push(o.nodes[idx.get(name)]);
    for (const e of o.edges.filter((x) => x.src === name)) {
      if (--deg[idx.get(e.dst)] === 0)
        stack.push(e.dst);
    }
  }
  return out;
}
async function evaluate(o, reg, input) {
  const trace = [];
  const value = new Map;
  const root = o.sink || o.nodes.find((n) => !o.edges.some((e) => e.src === n.name))?.name || "";
  for (const n of topo(o)) {
    const feed = o.edges.filter((e) => e.dst === n.name).map((e) => {
      const v = value.get(e.src);
      return { from: e.src, out: e.out, value: Array.isArray(v) ? v[e.out] : v };
    });
    let got;
    let error;
    let note2 = "";
    try {
      const said = unwrap(await reg.get(n.handle).call({ node: n.name, moment: n.moment, domain: domainText(n.domain), feed, input }));
      got = said.value;
      note2 = said.note;
      const bad = checkValue(n.domain, got);
      if (bad) {
        error = `out of contract: ${bad}`;
        got = n.domain.kind === "bool" ? false : Array.from({ length: n.domain.width }, () => false);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      got = n.domain.kind === "bool" ? false : Array.from({ length: n.domain.width }, () => false);
    }
    value.set(n.name, got);
    if (got === true)
      note2 = "";
    trace.push({ node: n.name, value: got, ...error ? { error } : {}, ...note2 ? { note: note2 } : {} });
  }
  const out = value.get(root);
  const broke = trace.filter((t) => t.error);
  const valid = broke.length === 0 && typeof out === "boolean";
  const pass = valid && out === true ? 1 : 0;
  const note = pass === 1 ? "" : trace.filter((t) => t.note).map((t) => `${t.node}: ${t.note}`).join("; ");
  return {
    pass,
    valid,
    outcome: valid ? pass === 1 ? "passed" : "rejected" : "grader_error",
    why: pass === 1 ? "" : note ? "see note" : broke.length ? broke.map((t) => `${t.node}: ${t.error}`).join("; ") : `${root} evaluated to false`,
    note,
    trace
  };
}
var init_run = __esm(() => {
  init_spec();
});

// scripts/benchmark-repair/campaign-contract.ts
function checkedOutputTokens(body) {
  const values = [body.max_tokens, body.max_completion_tokens].filter((value) => value !== undefined && value !== null);
  if (!values.length || values.some((value) => !count(value) || value < 1 || value > MAX_OUTPUT_TOKENS))
    throw new Error(`Output token limit must be a finite positive integer at most ${MAX_OUTPUT_TOKENS}`);
  if (values.length > 1 && values[0] !== values[1])
    throw new Error("Conflicting output token limits");
  return values[0];
}
function completionFault(value) {
  const data = object(value);
  if (!data || data.error)
    return "InvalidCompletionEnvelope";
  if (!Array.isArray(data.choices) || data.choices.length === 0)
    return "MissingCompletionChoices";
  for (const entry of data.choices) {
    const choice = object(entry), message = object(choice?.message);
    if (!message || message.role !== "assistant")
      return "InvalidCompletionMessage";
    const tools = message.tool_calls;
    if (tools !== undefined && tools !== null) {
      if (!Array.isArray(tools))
        return "InvalidCompletionToolCalls";
      for (const item of tools) {
        const call = object(item), fn = object(call?.function);
        if (call?.type !== "function" || typeof call.id !== "string" || !call.id || typeof fn?.name !== "string" || !fn.name || typeof fn.arguments !== "string")
          return "InvalidCompletionToolCall";
      }
    }
    const hasText = typeof message.content === "string";
    const hasTools = Array.isArray(tools) && tools.length > 0;
    const hasReasoning = [message.reasoning_content, message.reasoning].some((value2) => typeof value2 === "string" && value2.length > 0);
    if (!hasText && !hasTools && !hasReasoning)
      return "MissingCompletionMessagePayload";
    if (message.content !== undefined && message.content !== null && !hasText)
      return "InvalidCompletionContent";
  }
  return;
}
function usageCounts(value) {
  const usage = object(value);
  const input = usage?.prompt_tokens, output = usage?.completion_tokens;
  const cached = usage?.prompt_cache_hit_tokens ?? object(usage?.prompt_tokens_details)?.cached_tokens ?? 0;
  if (!count(input) || !count(output) || !count(cached) || cached > input)
    throw new Error("InvalidProviderTokenUsage");
  return { input, output, cached };
}
function validTokenUsage(value) {
  try {
    usageCounts(value);
    return true;
  } catch {
    return false;
  }
}
function tokenCostUpperBound(usage, rates = PEAK_RATES) {
  if (Object.values(rates).some((rate) => !Number.isFinite(rate) || rate < 0))
    throw new Error("Invalid frozen price rates");
  const { input, output, cached } = usageCounts(usage);
  return ((input - cached) * rates.input + cached * rates.cachedInput + output * rates.output) / 1e6;
}
function isNonGenerationRateRejection(call) {
  return call.nonGenerationRejection === "upstream_rate_limit" && call.httpStatus === 429 && call.providerAttempted === true && call.costBasis === "known_uncharged" && call.usdUpperBound === 0 && !call.usage && !call.requestId && !call.fault && !!call.finishedAt;
}
function reconcileReceiptCost(receipt, reservationUsd, options = {}) {
  if (!Number.isFinite(reservationUsd) || reservationUsd < 0)
    throw new Error("Invalid request cost reservation");
  const before = receipt.accountedUpperBoundUsd ?? 0;
  if (!Number.isFinite(before) || before < 0)
    throw new Error("Invalid accounted request cost");
  let upper = reservationUsd;
  let basis = options.knownUncharged ? "known_uncharged" : "reservation";
  if (options.knownUncharged)
    upper = 0;
  if (options.provider && !options.knownUncharged) {
    const usage = object(receipt.usage), cost = usage?.cost;
    if (typeof cost === "number" && Number.isFinite(cost) && cost >= 0) {
      upper = cost;
      basis = "provider_reported_usd";
      receipt.billedCostUsd = cost;
      if (!validTokenUsage(usage))
        receipt.fault ??= "InvalidProviderTokenUsage";
    } else {
      receipt.fault ??= "MissingOrInvalidOpenRouterUsdCost";
    }
  } else if (receipt.usage !== undefined) {
    if (validTokenUsage(receipt.usage)) {
      upper = tokenCostUpperBound(receipt.usage, options.rates);
      basis = "reported_usage";
    } else {
      upper = reservationUsd;
      basis = "reservation";
      receipt.fault ??= "InvalidProviderTokenUsage";
    }
  }
  receipt.reservationUsd = reservationUsd;
  receipt.usdUpperBound = upper;
  receipt.accountedUpperBoundUsd = upper;
  receipt.costBasis = basis;
  return { usdUpperBound: upper, deltaUsd: upper - before, costBasis: basis };
}
var MAX_OUTPUT_TOKENS = 16384, PEAK_RATES, object = (value) => value !== null && typeof value === "object" && !Array.isArray(value) ? value : undefined, count = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
var init_campaign_contract = __esm(() => {
  init_registry();
  init_run();
  init_spec();
  PEAK_RATES = Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 });
});

// scripts/benchmark-repair/campaign-workers.ts
var MiB;
var init_campaign_workers = __esm(() => {
  MiB = 1024 * 1024;
});

// scripts/benchmark-repair/scientific-journal-plan.ts
import { createHash as createHash2 } from "crypto";
var digest = (data) => createHash2("sha256").update(data).digest("hex");
var init_scientific_journal_plan = __esm(() => {
  init_campaign_workers();
});

// scripts/benchmark-repair/benchmark-provider.ts
function officialOpenRouterFault(data, expectedProvider = BENCHMARK_PROVIDER.providerName) {
  if (data?.provider !== expectedProvider)
    return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER.model, BENCHMARK_PROVIDER.canonicalModel].includes(data?.model))
    return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id)
    return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0)
    return "MissingOrInvalidOpenRouterUsdCost";
}
function openRouterRateLimitRejection(data, status, providerName) {
  return status === 429 && data?.error?.code === 429 && data.error.metadata?.limit_source === "upstream_provider_shared_pool" && data.error.metadata.provider_name === providerName && typeof data.error.metadata.raw === "string" && data.error.metadata.raw.includes("temporarily rate-limited upstream") && !data.id && !data.usage && !data.choices;
}
var BENCHMARK_PROVIDER;
var init_benchmark_provider = __esm(() => {
  BENCHMARK_PROVIDER = Object.freeze({
    kind: "openrouter-deepseek",
    model: "deepseek/deepseek-v4.1-flash",
    canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
    baseURL: "https://openrouter.ai/api/v1",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    keyEnv: "OPENROUTER_API_KEY",
    currency: "USD",
    providerName: "Relace",
    providerSlug: "relace",
    peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
    routing: Object.freeze({ only: ["relace"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
    forcedToolMode: "constrained-auto"
  });
});

// scripts/benchmark-repair/benchmark-inference.ts
function benchmarkProviderRequest(body, profile = BENCHMARK_INFERENCE, provider) {
  const choice = body.tool_choice;
  const forced = choice === "required" || choice?.type === "function" && typeof choice.function?.name === "string";
  const effort = provider ? profile.reasoningEffort : forced ? "none" : profile.reasoningEffort;
  const thinking = forced ? "disabled" : "enabled";
  const limits = [body.max_tokens, body.max_completion_tokens].filter((value) => value !== undefined && value !== null);
  if (body.temperature !== profile.temperature || body.seed !== profile.seed && !(provider && body.seed === undefined) || body.reasoning_effort !== effort || !limits.length || limits.some((value) => value !== profile.maxTokens) || body.thinking !== undefined && body.thinking?.type !== (provider ? "enabled" : thinking)) {
    throw new Error("Wire parameters differ from the benchmark inference profile");
  }
  const wire = { ...body, thinking: { type: thinking }, max_tokens: profile.maxTokens };
  delete wire.max_completion_tokens;
  if (provider) {
    if (body.model !== provider.model || profile.reasoningEffort !== "high")
      throw Error("OpenRouter V4.1 Flash high-thinking profile required");
    if (forced) {
      const name = choice?.function?.name;
      if (typeof name !== "string")
        throw Error("Constrained auto submission requires a named tool");
      wire.tools = (body.tools ?? []).filter((tool) => tool.type === "function" && tool.function?.name === name);
      if (wire.tools.length !== 1)
        throw Error("The required submit tool is absent or duplicated");
      wire.tool_choice = "auto";
    }
    wire.provider = { ...BENCHMARK_PROVIDER.routing };
    wire.reasoning = { enabled: true, effort: "high", exclude: false };
    delete wire.thinking;
    delete wire.reasoning_effort;
    delete wire.seed;
  }
  return wire;
}
var BENCHMARK_INFERENCE;
var init_benchmark_inference = __esm(() => {
  init_benchmark_provider();
  BENCHMARK_INFERENCE = Object.freeze({
    maxTokens: 16384,
    reasoningEffort: "high",
    temperature: 0,
    seed: 42,
    retryTimes: 3,
    continueTimes: 3
  });
});

// scripts/benchmark-repair/scientific-journal-proxy.ts
import { closeSync as closeSync2, fsyncSync, mkdirSync as mkdirSync2, openSync as openSync2, writeFileSync } from "fs";
import { join as join2 } from "path";
import { gzipSync } from "zlib";

class ScientificJournalProxy {
  journal;
  options;
  stopReason;
  flights = new Map;
  taskReceipts = new Map;
  anomalyOrdinal = 0;
  anomalies = [];
  constructor(journal, options) {
    this.journal = journal;
    this.options = options;
  }
  stop(reason) {
    this.stopReason ??= reason;
  }
  state() {
    return { stopReason: this.stopReason, activeHandlers: this.flights.size, anomalies: this.anomalies.length, journal: this.journal.snapshot() };
  }
  pending(route) {
    return [...this.flights.values()].filter((value) => value === route).length;
  }
  async drain(route) {
    while (true) {
      const current = [...this.flights].filter(([, value]) => route === undefined || route === value).map(([promise]) => promise);
      if (!current.length)
        return;
      await Promise.allSettled(current);
    }
  }
  takeTaskReceipts(route) {
    if (this.pending(route))
      throw new Error("Task transport has not drained");
    const receipts = this.taskReceipts.get(route) ?? [];
    this.taskReceipts.delete(route);
    return receipts.sort((a, b) => a.requestSeq - b.requestSeq);
  }
  handle(route, raw) {
    const job = this.perform(route, raw);
    this.flights.set(job, route);
    job.then(() => this.flights.delete(job), () => this.flights.delete(job));
    return job;
  }
  async fallback(input) {
    const snapshot = this.journal.snapshot();
    const receipt = {
      providerAttempted: input.finish?.providerAttempted ?? false,
      ...input.finish?.httpStatus !== undefined ? { httpStatus: input.finish.httpStatus } : {},
      fault: "journal_failure",
      finishedAt: input.finish?.finishedAt ?? new Date().toISOString()
    };
    let usage;
    if (input.finish?.rawResponse !== undefined) {
      try {
        usage = JSON.parse(input.finish.rawResponse).usage;
        if (usage && typeof usage === "object")
          receipt.usage = usage;
      } catch {}
    }
    const facts = {
      schemaVersion: 1,
      stage: input.stage,
      route: input.route,
      requestSeq: input.admitted?.requestSeq,
      providerAttempted: input.finish?.providerAttempted ?? false,
      confirmedNoForward: !input.finish?.providerAttempted,
      httpStatus: input.finish?.httpStatus,
      observedAt: new Date().toISOString(),
      requestSha256: input.admitted?.requestSha256 ?? (input.rawRequest === undefined ? undefined : digest(input.rawRequest)),
      rawResponseSha256: input.rawResponseBytes ? digest(input.rawResponseBytes) : input.finish?.rawResponse === undefined ? undefined : digest(input.finish.rawResponse),
      bodyComplete: input.rawResponseBytes ? false : undefined,
      journalRef: input.journalRef,
      usage,
      independentCost: reconcileReceiptCost(receipt, input.admitted?.reservationUsd ?? 0, { knownUncharged: !input.finish?.providerAttempted }),
      accounting: "Independent transport facts only. Original poisoned journal/pending/reserve are not repaired. Cost may overlap a durable finish; auditor must reconcile call ID before adding liability.",
      journalSnapshot: snapshot,
      error: input.error instanceof Error ? input.error.name : "JournalFailure",
      files: [],
      evidenceWriteError: undefined
    };
    const sequence = this.anomalyOrdinal++;
    const persist = (name, data) => {
      const path = join2(this.options.failureDirectory, `failure-${sequence}-${name}`), fd = openSync2(path, "wx", 384);
      try {
        writeFileSync(fd, data);
        fsyncSync(fd);
      } finally {
        closeSync2(fd);
      }
      return { path, bytes: data.byteLength, sha256: digest(data) };
    };
    try {
      mkdirSync2(this.options.failureDirectory, { recursive: true });
      if (input.rawRequest !== undefined)
        facts.files.push(persist("request.json.gz", gzipSync(input.rawRequest)));
      if (input.rawResponseBytes || input.finish?.rawResponse !== undefined)
        facts.files.push(persist("response.json.gz", gzipSync(input.rawResponseBytes ?? input.finish.rawResponse)));
      facts.files.push(persist("receipt.json", Buffer.from(JSON.stringify(facts, null, 2) + `
`)));
    } catch (error) {
      facts.evidenceWriteError = error instanceof Error ? error.name : "FailureEvidenceIo";
    }
    this.anomalies.push(facts);
    this.stop("journal_poison_or_evidence_failure");
    try {
      await this.options.afterFailedJournalCapture?.(input.admitted, input.finish, facts);
    } catch {
      facts.evidenceWriteError ??= "CashShadowLateCaptureFailure";
    }
  }
  async perform(route, raw) {
    const rejected = (status, why) => ({ httpStatus: status, rawResponse: JSON.stringify({ error: { message: why } }) });
    let admitted;
    try {
      if (!this.options.routes.has(route))
        return rejected(404, "Unplanned model route");
      let body = JSON.parse(raw);
      if (this.options.inference) {
        body = benchmarkProviderRequest(body, this.options.inference, this.options.provider);
        raw = JSON.stringify(body);
      }
      if (body.model !== (this.options.provider?.model ?? "deepseek-flash") || body.stream === true || body.temperature !== 0 || !this.options.provider && body.seed !== 42 || !this.options.inference && (body.reasoning_effort !== "none" || checkedOutputTokens(body) !== 8192))
        throw new Error("Wire parameters differ from the fixed scientific protocol");
      checkedOutputTokens(body);
      const started = Date.now();
      while (!admitted) {
        if (this.stopReason)
          return rejected(503, "Admission stopped: " + this.stopReason);
        this.options.beforeAdmission?.();
        const value = this.journal.admit({ route, rawRequest: raw });
        if (value.admitted)
          admitted = value;
        else if (value.reason !== "pending_limit") {
          this.stop(value.reason);
          return rejected(503, "Admission stopped: " + value.reason);
        } else {
          if (Date.now() - started > (this.options.waitMs ?? 300000)) {
            this.stop("admission_queue_timeout");
            return rejected(503, "Admission queue timed out");
          }
          await Bun.sleep(10);
        }
      }
    } catch (error) {
      await this.fallback({ stage: "admission", route, rawRequest: raw, error });
      return rejected(503, "Request was not forwarded; journal or protocol admission failed");
    }
    let response, fault, forwarded = false;
    let bodyFailure;
    try {
      await this.options.beforeForward?.(admitted, this.journal.snapshot().durablePrefix, raw, route);
      if (this.stopReason)
        throw new Error("Admission stopped before provider dispatch");
      forwarded = true;
      response = await this.options.transport(raw);
    } catch (error) {
      fault = error instanceof Error ? error.name : "ProviderTransportError";
      if (error instanceof ConfirmedNoForwardTransportFailure)
        forwarded = false;
      if (error instanceof CapturedTransportFailure) {
        bodyFailure = error;
        try {
          response = { httpStatus: error.capture.httpStatus, rawResponse: new TextDecoder("utf-8", { fatal: true }).decode(error.capture.rawBytes) };
        } catch {}
      }
      this.stop(forwarded ? "provider_transport_error" : "funding_before_forward_error");
    }
    const finish = {
      requestSeq: admitted.requestSeq,
      providerAttempted: forwarded,
      ...!forwarded ? { confirmedNoForward: true } : {},
      ...response ?? {},
      ...bodyFailure ? { httpStatus: bodyFailure.capture.httpStatus } : {},
      ...fault ? { fault } : {},
      finishedAt: new Date().toISOString()
    };
    let durableReceipt;
    try {
      const before = this.journal.snapshot().durablePrefix.bytes;
      const result = this.journal.finish(finish);
      const prefix = this.journal.snapshot().durablePrefix;
      const receipt = { ...result.receipt, requestSeq: result.requestSeq, journalRef: { callId: result.requestSeq, finishOffset: before, finishEnd: prefix.bytes, finishLineSha256: prefix.lastSha256 } };
      durableReceipt = receipt;
      await this.options.afterDurableFinish?.(receipt);
      if (bodyFailure)
        await this.fallback({ stage: "provider_body_incomplete", route, admitted, finish, journalRef: receipt.journalRef, rawResponseBytes: bodyFailure.capture.rawBytes, error: bodyFailure });
      const records = this.taskReceipts.get(route) ?? [];
      records.push(receipt);
      this.taskReceipts.set(route, records);
      if (this.journal.snapshot().stopReason)
        this.stop(this.journal.snapshot().stopReason);
      return !fault && response ? response : rejected(503, "Provider transport did not complete; conservative request charge retained");
    } catch (error) {
      await this.fallback({ stage: "finish_or_post_finish_checkpoint", route, admitted, finish, journalRef: durableReceipt?.journalRef, rawResponseBytes: bodyFailure?.capture.rawBytes, error });
      return rejected(503, "Transport finished but journal remains invalid; actual response captured independently");
    }
  }
}
var CapturedTransportFailure, ConfirmedNoForwardTransportFailure;
var init_scientific_journal_proxy = __esm(() => {
  init_campaign_contract();
  init_scientific_journal_plan();
  init_benchmark_inference();
  CapturedTransportFailure = class CapturedTransportFailure extends Error {
    capture;
    constructor(capture) {
      super(capture.fault);
      this.capture = capture;
      this.name = capture.fault;
    }
  };
  ConfirmedNoForwardTransportFailure = class ConfirmedNoForwardTransportFailure extends Error {
    constructor(message) {
      super(message);
      this.name = "ConfirmedNoForwardTransportFailure";
    }
  };
});

// scripts/benchmark-repair/campaign-journal.ts
import { createHash as createHash4, randomBytes as randomBytes2 } from "crypto";
import { closeSync as closeSync5, existsSync as existsSync3, fstatSync as fstatSync2, fsyncSync as fsyncSync4, lstatSync as lstatSync3, mkdirSync as mkdirSync6, openSync as openSync5, readFileSync as readFileSync4, readSync as readSync3, readdirSync as readdirSync2, realpathSync as realpathSync3, renameSync as renameSync2, statSync as statSync4, writeSync as writeSync2 } from "fs";
import { isAbsolute as isAbsolute3, join as join6, relative as relative3, resolve as resolve6 } from "path";
import { gunzipSync as gunzipSync3, gzipSync as gzipSync3 } from "zlib";
function demand3(ok, code) {
  if (!ok)
    throw new CampaignJournalError2(code);
}
function ordinaryDirectory3(path) {
  demand3(isAbsolute3(path), "absolute_directory_required");
  mkdirSync6(path, { recursive: true });
  demand3(lstatSync3(path).isDirectory() && !lstatSync3(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync3(path);
}
function regularInStore2(path, store) {
  const full = resolve6(path), rel = relative3(store, full);
  demand3(rel && !rel.startsWith("..") && !isAbsolute3(rel), "raw_outside_store");
  let current = store;
  for (const component of rel.split(/[\\/]/)) {
    current = join6(current, component);
    const s = lstatSync3(current);
    demand3(!s.isSymbolicLink(), "raw_reparse");
  }
  demand3(lstatSync3(full).isFile() && realpathSync3(full) === full, "raw_not_regular");
  return full;
}
function fileHash3(path) {
  const before = statSync4(path), fd = openSync5(path, "r"), digest2 = createHash4("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync3(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand3(n > 0, "hash_short_read");
      digest2.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync5(fd);
  }
  const after = statSync4(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest2.digest("hex");
}
function rawEvidence2(path, expected, compressedExpected, store, parse = true) {
  regularInStore2(path, store);
  const before = statSync4(path);
  const zipped = readFileSync4(path);
  demand3(zipped.length <= MAX_RESPONSE2 + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync3(zipped, { maxOutputLength: MAX_RESPONSE2 });
  const after = statSync4(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash3(zipped) === compressedExpected && hash3(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting2(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand3(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand3(["deepseek", "relace"].includes(slug) && (config.providerName === undefined || config.providerName === (slug === "relace" ? "Relace" : "DeepSeek")), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand3(config.providerRouting === undefined || same3(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues3(raw, data, config) {
  demand3(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand3(same3(data.provider, frozenRouting2(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
  const limit = checkedOutputTokens(data);
  demand3(Array.isArray(data.messages), "invalid_request_messages");
  const reservationUsd = ((raw.length + 2048 + data.messages.length * 256) * 0.3 + limit * 1.2) / 1e6;
  return { reservationUsd, wireParameters: Object.fromEntries(WIRE2.filter((k) => (k in data)).map((k) => [k, data[k]])) };
}
function checkedStart2(c, seq, store, config) {
  demand3(typeof c.route === "string" && c.route.length > 0 && Buffer.byteLength(c.route) <= 1024 && !/[\r\n\0]/.test(c.route), "invalid_route");
  demand3(Number.isFinite(Date.parse(c.startedAt)) && c.providerAttempted === false, "invalid_start_receipt");
  demand3(c.requestFile === join6(store, `provider-${seq}-request.json.gz`), "request_sequence_path");
  const { raw, data } = rawEvidence2(c.requestFile, c.requestSha256, c.requestCompressedSha256, store);
  const expected = requestValues3(raw, data, config);
  demand3(raw.length === c.requestBytes && c.requestedModel === data.model && same3(c.wireParameters, expected.wireParameters) && finite2(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS2, "request_receipt_mismatch");
}
function routingRejection2(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection2(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish2(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand3(same3(c[key], start[key]), "finish_start_mismatch");
  demand3(typeof c.providerAttempted === "boolean" && typeof c.finishedAt === "string" && Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
  if (!c.providerAttempted)
    demand3(c.confirmedNoForward === true && !c.responseFile && !c.usage, "unproven_zero_charge");
  let rejectedBeforeGeneration = false, rateLimited = false;
  if (c.responseFile) {
    demand3(c.providerAttempted && c.responseFile === join6(store, `provider-${seq}-response.json.gz`) && c.responseSha256 && c.responseCompressedSha256, "response_sequence_path");
    const { raw } = rawEvidence2(c.responseFile, c.responseSha256, c.responseCompressedSha256, store, false);
    let data;
    try {
      data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {}
    if (data && typeof data === "object") {
      rejectedBeforeGeneration = routingRejection2(config, data, c.httpStatus);
      rateLimited = rateRejection2(config, data, c.httpStatus);
      demand3(same3(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
      if (config.provider) {
        demand3((typeof data.provider === "string" ? data.provider : undefined) === c.providerName, "provider_receipt_mismatch");
        const routeFault = c.httpStatus === 200 ? officialOpenRouterFault(data, config.providerName ?? "DeepSeek") : undefined;
        if (routeFault)
          demand3(c.fault === routeFault, "official_provider_fault_missing");
      }
      if (c.httpStatus === 200)
        demand3(c.completionValid === !completionFault(data) && c.completionFault === completionFault(data), "completion_receipt_mismatch");
    } else
      demand3(c.fault && c.usage === undefined && c.servedModel === undefined && c.requestId === undefined && c.completionValid === undefined, "invalid_json_receipt_mismatch");
  } else
    demand3(c.fault && !c.usage && c.servedModel === undefined && c.requestId === undefined, "missing_response_evidence");
  demand3(c.nonGenerationRejection === (rateLimited ? "upstream_rate_limit" : undefined), "rate_rejection_raw_binding");
  const expected = { usage: c.usage };
  reconcileReceiptCost(expected, start.reservationUsd, { provider: config.provider, knownUncharged: rateLimited || rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
  demand3(c.billedCostUsd === expected.billedCostUsd, "reported_usd_cost_mismatch");
  demand3(c.reservationUsd === start.reservationUsd && c.costBasis === expected.costBasis && finite2(c.usdUpperBound) && finite2(c.accountedUpperBoundUsd) && Math.abs(c.usdUpperBound - expected.usdUpperBound) <= EPS2 && c.usdUpperBound === c.accountedUpperBoundUsd, "cost_receipt_mismatch");
}
function pendingOf2(active) {
  const result = new Map;
  for (const c of active.values())
    result.set(c.route, (result.get(c.route) ?? 0) + 1);
  return Object.fromEntries(result);
}
function reserveOf2(active) {
  let n = 0;
  for (const c of active.values())
    n += c.reservationUsd;
  return n;
}
function financialState2(config, configSha256, active, accepted, finished, spent, prefix, stopReason) {
  return { protocol: config.protocol, ...config.provider ? { currency: "USD", provider: config.provider } : {}, campaign: config.campaign, configSha256, capUsd: config.capUsd, priorCampaignCostUpperBoundUsd: config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserveOf2(active), pending: pendingOf2(active), active: [...active].map(([requestSeq, c]) => ({ requestSeq, route: c.route, requestSha256: c.requestSha256, reservationUsd: c.reservationUsd })), acceptedRequestCount: accepted, finishedRequestCount: finished, durablePrefix: { ...prefix }, ...stopReason ? { stopReason } : {} };
}
function* lines2(fd, length) {
  let offset = 0, at = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at < length) {
    const n = readSync3(fd, buffer, 0, Math.min(buffer.length, length - at), at);
    demand3(n > 0, "journal_short_read");
    at += n;
    carry = Buffer.concat([carry, buffer.subarray(0, n)]);
    for (;; ) {
      const newline = carry.indexOf(10);
      if (newline < 0)
        break;
      const line = carry.subarray(0, newline + 1);
      demand3(line.length <= MAX_LINE2, "journal_line_limit");
      yield { offset, line };
      offset += line.length;
      carry = carry.subarray(newline + 1);
    }
    demand3(carry.length <= MAX_LINE2, "journal_line_limit");
  }
  demand3(carry.length === 0, "truncated_journal");
}
function inspectCampaignJournal2(directory) {
  return inspect2(directory);
}
function inspect2(directory, ownedExport) {
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join6(resolve6(directory), "api-events.jsonl"), directory: resolve6(directory) };
  let fd;
  try {
    const store = realpathSync3(directory);
    demand3(store === resolve6(directory), "journal_directory_identity");
    const configBytes = readFileSync4(join6(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL2 && config.model === BENCHMARK_PROVIDER.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL2 && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting2(config);
    demand3(providerValid && config.pendingLimit === 4 && config.maxLineBytes === MAX_LINE2 && config.maxJournalBytes === MAX_JOURNAL2 && finite2(config.capUsd) && config.capUsd > 0 && finite2(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash3(configBytes), before = statSync4(result.journalPath);
    demand3(before.size <= MAX_JOURNAL2 && lstatSync3(result.journalPath).isFile() && !lstatSync3(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync5(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines2(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand3(same3(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json2(e) + `
`).equals(line), "unknown_or_noncanonical_event");
      demand3(e.protocol === config.protocol && e.eventSeq === prefix.eventCount && e.previousEventSha256 === prefix.lastSha256 && Number.isSafeInteger(e.requestSeq) && e.requestSeq >= 0, "journal_chain_or_sequence");
      if (e.kind === "start") {
        demand3(e.requestSeq === accepted && active.size < 4 && !active.has(e.requestSeq), "duplicate_or_unbounded_start");
        checkedStart2(e.record, e.requestSeq, store, config);
        demand3(config.priorCampaignCostUpperBoundUsd + spent + reserveOf2(active) + e.record.reservationUsd <= config.capUsd + EPS2, "admission_exceeded_cap");
        active.set(e.requestSeq, e.record);
        accepted++;
      } else if (e.kind === "finish") {
        const start = active.get(e.requestSeq);
        demand3(start && !result.offsets.has(e.requestSeq), "duplicate_or_unknown_finish");
        checkedFinish2(e.record, start, e.requestSeq, store, config);
        if (e.record.requestId) {
          demand3(!ids.has(e.record.requestId), "duplicate_provider_id");
          ids.add(e.record.requestId);
        }
        spent += e.record.usdUpperBound;
        active.delete(e.requestSeq);
        finished++;
        allProviderValid &&= isNonGenerationRateRejection(e.record) || e.record.providerAttempted && e.record.httpStatus === 200 && e.record.completionValid === true && validTokenUsage(e.record.usage) && !e.record.fault;
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash3(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError2("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash3(line) };
      result.snapshot = financialState2(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState2(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync4(join6(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand3(same3(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync2(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync2(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand3(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand3(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand3(ownedExport.path === join6(store, "api-ledger.json.partial") && statSync4(ownedExport.path).size === ownedExport.bytes && fileHash3(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand3(!existsSync3(join6(store, "journal-error.json")) && !readdirSync2(store).some((n) => n.includes(".partial") && join6(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync4(result.journalPath);
    demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash3(readFileSync4(join6(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS2;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError2 ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync5(fd);
  }
  return result;
}

class CampaignJournal2 {
  hooks;
  directory;
  outputDirectory;
  config;
  configSha256;
  journalPath;
  fd = -1;
  prefix;
  journalMtime = 0;
  lastLine;
  active = new Map;
  accepted = 0;
  finished = 0;
  spent = 0;
  stopReason;
  poisoned;
  exported = false;
  closedProof;
  closed = false;
  providerIds = new Set;
  metrics = { journalBytesWritten: 0, checkpointBytesWritten: 0, rawGzipBytesWritten: 0, exportBytesWritten: 0, fsyncCallsReturned: 0, maxHotMetadataBytes: 0 };
  constructor(options, hooks) {
    this.hooks = hooks;
    demand3(finite2(options.capUsd) && options.capUsd > 0 && finite2(options.priorCampaignCostUpperBoundUsd) && /^repair-[0-9TZ-]+$/.test(options.campaign), "invalid_journal_options");
    this.directory = ordinaryDirectory3(resolve6(options.directory));
    this.outputDirectory = ordinaryDirectory3(resolve6(options.outputDirectory ?? options.directory));
    demand3(!readdirSync2(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
    if (options.provider)
      demand3(options.provider.kind === BENCHMARK_PROVIDER.kind && options.provider.model === BENCHMARK_PROVIDER.model, "unsupported_journal_provider");
    this.config = { protocol: options.provider ? OPENROUTER_JOURNAL_PROTOCOL2 : CAMPAIGN_JOURNAL_PROTOCOL2, campaign: options.campaign, capUsd: options.capUsd, priorCampaignCostUpperBoundUsd: options.priorCampaignCostUpperBoundUsd, pendingLimit: 4, model: options.provider?.model ?? "deepseek-flash", ...options.provider ? {
      provider: options.provider.kind,
      currency: "USD",
      providerName: options.provider.providerName,
      providerSlug: options.provider.providerSlug,
      providerRouting: options.provider.routing,
      zeroChargePolicy: "explicit-rate-rejection-v2"
    } : {}, maxLineBytes: MAX_LINE2, maxJournalBytes: MAX_JOURNAL2, createdAt: new Date().toISOString() };
    const configRaw = Buffer.from(JSON.stringify(this.config, null, 2) + `
`);
    this.configSha256 = hash3(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join6(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join6(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync5(this.journalPath, "wx+");
      this.sync(this.fd, this.journalPath, "journal:create");
      this.journalMtime = fstatSync2(this.fd).mtimeMs;
      this.checkpoint("create");
    } catch (e) {
      this.close();
      if (e instanceof CampaignJournalError2)
        throw e;
      throw new CampaignJournalError2("journal_create_io", e.code);
    }
  }
  write(fd, path, raw, stage, metric) {
    let at = 0;
    while (at < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at };
      this.hooks.before?.(op);
      const n = writeSync2(fd, raw, at, raw.length - at);
      demand3(n > 0, "short_write");
      this.metrics[metric] += n;
      at += n;
      this.hooks.after?.({ ...op, bytes: n });
    }
  }
  sync(fd, path, stage) {
    const op = { kind: "fsync", stage, path, fd };
    this.hooks.before?.(op);
    fsyncSync4(fd);
    this.metrics.fsyncCallsReturned++;
    this.hooks.after?.(op);
  }
  persistExclusive(path, raw, stage, metric) {
    const fd = openSync5(path, "wx", 384);
    try {
      this.write(fd, path, raw, stage, metric);
      this.sync(fd, path, stage);
    } finally {
      try {
        closeSync5(fd);
      } catch {}
    }
  }
  state() {
    return financialState2(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason);
  }
  snapshot() {
    return { ...this.state(), ...this.poisoned ? { error: this.poisoned.code } : {}, metrics: { ...this.metrics } };
  }
  poison(code, stage, uncommittedReceipt) {
    const error = this.poisoned ?? new CampaignJournalError2(code, stage);
    this.poisoned = error;
    try {
      this.persistExclusive(join6(this.directory, "journal-error.json"), Buffer.from(json2({ protocol: CAMPAIGN_JOURNAL_PROTOCOL2, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
`), "error_diagnostic", "checkpointBytesWritten");
    } catch {}
    throw error;
  }
  writable() {
    if (this.poisoned)
      throw new CampaignJournalError2("journal_poisoned", this.poisoned.code);
    demand3(!this.closed, "writer_closed");
    demand3(!this.exported, "already_exported");
    try {
      const checkpointPath = join6(this.directory, "api-state.json");
      regularInStore2(checkpointPath, this.directory);
      const checkpoint = readFileSync4(checkpointPath);
      if (checkpoint.length > MAX_LINE2 || !checkpoint.equals(Buffer.from(json2(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync3(join6(this.directory, "journal-error.json")))
      this.poison("journal_changed", "unexpected_error_marker");
    try {
      regularInStore2(join6(this.directory, "journal-config.json"), this.directory);
      if (fileHash3(join6(this.directory, "journal-config.json")) !== this.configSha256)
        this.poison("journal_changed", "config_changed");
    } catch {
      this.poison("journal_changed", "config_changed");
    }
    try {
      const s = fstatSync2(this.fd), disk = lstatSync3(this.journalPath);
      if (!disk.isFile() || disk.isSymbolicLink() || disk.ino !== s.ino || disk.dev !== s.dev || s.size !== this.prefix.bytes || s.mtimeMs !== this.journalMtime)
        this.poison("journal_changed", "before_append");
      if (this.lastLine) {
        const raw = Buffer.alloc(this.lastLine.bytes);
        const n = readSync3(this.fd, raw, 0, raw.length, this.lastLine.offset);
        if (n !== raw.length || hash3(raw) !== this.lastLine.sha256)
          this.poison("journal_changed", "last_durable_line");
      }
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison("journal_identity_io", "before_append");
    }
  }
  checkpoint(stage) {
    const target = join6(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes2(8).toString("hex");
    const raw = Buffer.from(json2(this.state()) + `
`);
    demand3(raw.length <= MAX_LINE2, "checkpoint_resource_limit");
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    try {
      this.persistExclusive(temp, raw, "checkpoint:" + stage, "checkpointBytesWritten");
      const op = { kind: "rename", stage: "checkpoint:" + stage, path: target };
      this.hooks.before?.(op);
      renameSync2(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("checkpoint_io", stage);
    }
  }
  append(kind, seq, receipt, apply) {
    const e = { protocol: this.config.protocol, eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, requestSeq: seq, record: receipt };
    const raw = Buffer.from(json2(e) + `
`);
    if (raw.length > MAX_LINE2 || this.prefix.bytes + raw.length > MAX_JOURNAL2)
      this.poison("journal_resource_limit", `${kind}:${seq}`, receipt);
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => {
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash3(raw) };
      this.lastLine = { offset, bytes: raw.length, sha256: this.prefix.lastSha256 };
      apply();
    };
    try {
      this.write(this.fd, this.journalPath, raw, `journal:${kind}:${seq}`, "journalBytesWritten");
      this.sync(this.fd, this.journalPath, `journal:${kind}:${seq}`);
    } catch {
      if (this.metrics.fsyncCallsReturned > fsyncBefore)
        commit();
      this.poison("journal_io", `${kind}:${seq}`, receipt);
    }
    commit();
    try {
      this.journalMtime = fstatSync2(this.fd).mtimeMs;
    } catch {
      this.poison("journal_identity_io", `${kind}:${seq}`, receipt);
    }
    this.checkpoint(`${kind}:${seq}`);
  }
  admit(input) {
    this.writable();
    if (this.stopReason)
      return { admitted: false, reason: this.stopReason };
    if (this.active.size >= 4)
      return { admitted: false, reason: "pending_limit" };
    demand3(typeof input.rawRequest === "string" && Buffer.byteLength(input.rawRequest) <= MAX_REQUEST2, "request_resource_limit");
    demand3(typeof input.route === "string" && input.route.length > 0 && Buffer.byteLength(input.route) <= 1024 && !/[\r\n\0]/.test(input.route), "invalid_route");
    const raw = Buffer.from(input.rawRequest), data = JSON.parse(input.rawRequest), values = requestValues3(raw, data, this.config);
    if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf2(this.active) + values.reservationUsd > this.config.capUsd) {
      this.stopReason = "local_budget_exhausted";
      this.checkpoint("budget_stop");
      return { admitted: false, reason: this.stopReason };
    }
    const seq = this.accepted, requestFile = join6(this.directory, `provider-${seq}-request.json.gz`), zipped = gzipSync3(raw);
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash3(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash3(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
    demand3(Number.isFinite(Date.parse(c.startedAt)), "invalid_start_time");
    this.active.set(seq, c);
    try {
      this.persistExclusive(requestFile, zipped, `raw_request:${seq}`, "rawGzipBytesWritten");
    } catch {
      this.poison("raw_capture_io", `start:${seq}`, c);
    }
    this.append("start", seq, c, () => {
      this.accepted++;
    });
    return { admitted: true, requestSeq: seq, reservationUsd: values.reservationUsd, requestFile, requestSha256: c.requestSha256 };
  }
  finish(input) {
    this.writable();
    try {
      return this.finishReceipt(input);
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison(e instanceof CampaignJournalError2 ? e.code : "finish_input_error", "finish_input");
    }
  }
  finishReceipt(input) {
    const start = this.active.get(input.requestSeq);
    if (!start)
      this.poison(input.requestSeq < this.accepted ? "duplicate_finish" : "unknown_finish", "finish");
    const c = { ...start, providerAttempted: input.providerAttempted };
    demand3(typeof input.providerAttempted === "boolean", "invalid_provider_attempt");
    if (!input.providerAttempted) {
      demand3(input.confirmedNoForward === true && input.rawResponse === undefined, "unproven_zero_charge");
      c.confirmedNoForward = true;
    }
    if (input.httpStatus !== undefined) {
      demand3(Number.isInteger(input.httpStatus) && input.httpStatus >= 100 && input.httpStatus <= 599, "invalid_http_status");
      c.httpStatus = input.httpStatus;
    }
    let rejectedBeforeGeneration = false;
    if (input.rawResponse !== undefined) {
      demand3(input.providerAttempted && typeof input.rawResponse === "string" && Buffer.byteLength(input.rawResponse) <= MAX_RESPONSE2, "response_resource_limit");
      const raw = Buffer.from(input.rawResponse), zipped = gzipSync3(raw), responseFile = join6(this.directory, `provider-${input.requestSeq}-response.json.gz`);
      c.responseFile = responseFile;
      c.responseSha256 = hash3(raw);
      c.responseCompressedSha256 = hash3(zipped);
      try {
        this.persistExclusive(responseFile, zipped, `raw_response:${input.requestSeq}`, "rawGzipBytesWritten");
      } catch {
        this.poison("raw_capture_io", `finish:${input.requestSeq}`, c);
      }
      try {
        const data = JSON.parse(input.rawResponse);
        rejectedBeforeGeneration = routingRejection2(this.config, data, input.httpStatus);
        if (rateRejection2(this.config, data, input.httpStatus)) {
          c.nonGenerationRejection = "upstream_rate_limit";
          rejectedBeforeGeneration = true;
        }
        if (this.config.provider) {
          c.providerName = typeof data.provider === "string" ? data.provider : undefined;
          if (input.httpStatus === 200)
            c.fault = officialOpenRouterFault(data, this.config.providerName ?? "DeepSeek");
        }
        c.servedModel = typeof data.model === "string" ? data.model : undefined;
        c.requestId = typeof data.id === "string" ? data.id : undefined;
        if (data.usage && typeof data.usage === "object")
          c.usage = data.usage;
        if (input.httpStatus === 200) {
          c.completionFault = completionFault(data);
          c.completionValid = !c.completionFault;
        }
      } catch {
        c.fault = "InvalidProviderJSON";
      }
    }
    if (input.fault) {
      demand3(typeof input.fault === "string" && Buffer.byteLength(input.fault) <= 2048, "fault_resource_limit");
      c.fault = input.fault;
    }
    if (!c.responseFile && !c.fault)
      c.fault = input.providerAttempted ? "UncapturedProviderTransport" : "LocalBeforeForwardError";
    reconcileReceiptCost(c, start.reservationUsd, { provider: this.config.provider, knownUncharged: rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
    c.finishedAt = input.finishedAt ?? new Date().toISOString();
    demand3(Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
    if (c.requestId && this.providerIds.has(c.requestId))
      this.poison("duplicate_provider_id", "finish", c);
    this.append("finish", input.requestSeq, c, () => {
      this.spent += c.usdUpperBound;
      this.active.delete(input.requestSeq);
      this.finished++;
      if (c.requestId)
        this.providerIds.add(c.requestId);
      if (c.usdUpperBound > start.reservationUsd + EPS2)
        this.stopReason ??= "usage_exceeded_reservation";
      if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf2(this.active) > this.config.capUsd + EPS2)
        this.stopReason ??= "actual_cost_exceeded_cap";
      if (!isNonGenerationRateRejection(c) && (c.fault || c.httpStatus !== 200 || c.completionValid !== true || !validTokenUsage(c.usage)))
        this.stopReason ??= "provider_fault";
    });
    return { requestSeq: input.requestSeq, receipt: { ...c }, accountingCommitted: true };
  }
  readReceipt(fd, offset) {
    const line = Buffer.alloc(offset.bytes);
    demand3(readSync3(fd, line, 0, line.length, offset.offset) === line.length && hash3(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand3(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand3(statSync4(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync5(this.journalPath, "r");
    const indices = route === undefined ? Array.from({ length: this.accepted }, (_, i) => i) : [...proof.routes.get(route) ?? []].sort((a, b) => a - b);
    try {
      for (const seq of indices) {
        const offset = proof.offsets.get(seq);
        demand3(offset, "missing_finish_offset");
        const c = this.readReceipt(fd, offset);
        const start = { ...c, providerAttempted: false };
        checkedStart2(start, seq, this.directory, this.config);
        checkedFinish2(c, start, seq, this.directory, this.config);
        yield c;
      }
    } finally {
      closeSync5(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand3(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal2(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same3(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS2)
      this.poison("export_integrity", "before_export");
    const target = join6(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand3(!existsSync3(target) && !existsSync3(temp), "existing_export");
    const fd = openSync5(temp, "wx", 384), journalFd = openSync5(this.journalPath, "r");
    try {
      const header = { ...this.config.provider ? { protocol: this.config.protocol, currency: "USD", provider: this.config.provider, model: this.config.model } : {}, campaign: this.config.campaign, capUsd: this.config.capUsd, priorCampaignCostUpperBoundUsd: this.config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: this.spent, reservedUpperBoundUsd: 0, ...this.stopReason ? { fatal: this.stopReason } : {}, pending: {}, captureErrors: [], calls: [] };
      const opening = JSON.stringify(header, null, 2).replace(/\[\]\n}$/, `[
`);
      this.write(fd, temp, Buffer.from(opening), "legacy_export", "exportBytesWritten");
      for (let seq = 0;seq < this.accepted; seq++) {
        const offset = proof.offsets.get(seq);
        demand3(offset, "missing_finish_offset");
        const text = JSON.stringify(this.readReceipt(journalFd, offset), null, 2).split(`
`).map((line) => "    " + line).join(`
`);
        this.write(fd, temp, Buffer.from(text + (seq + 1 < this.accepted ? `,
` : `
`)), "legacy_export", "exportBytesWritten");
      }
      this.write(fd, temp, Buffer.from(`  ]
}
`), "legacy_export", "exportBytesWritten");
      this.sync(fd, temp, "legacy_export");
    } catch {
      this.poison("export_io", "legacy_export");
    } finally {
      try {
        closeSync5(fd);
      } catch {}
      closeSync5(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync4(temp).size, sha256: fileHash3(temp) } : undefined;
    const after = inspect2(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same3(after.prefix, proof.prefix))
      this.poison("export_integrity", "after_export");
    try {
      const op = { kind: "rename", stage: "legacy_export", path: target };
      this.hooks.before?.(op);
      renameSync2(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("export_io", "legacy_rename");
    }
    this.exported = true;
    this.closedProof = after;
    return { path: target, bytes: statSync4(target).size, sha256: fileHash3(target), accountingClosed: true, eligibleForScoreCertification: proof.eligibleForScoreCertification, durablePrefix: { ...this.prefix }, legacyCompletedNotSet: true };
  }
  close() {
    if (!this.closed) {
      try {
        closeSync5(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}
var CAMPAIGN_JOURNAL_PROTOCOL2 = "campaign-api-journal-v1", OPENROUTER_JOURNAL_PROTOCOL2 = "campaign-api-journal-openrouter-v1", MAX_LINE2, MAX_REQUEST2, MAX_RESPONSE2, MAX_JOURNAL2, EPS2 = 0.000000001, WIRE2, hash3 = (data) => createHash4("sha256").update(data).digest("hex"), json2 = (value) => JSON.stringify(value), same3 = (a, b) => json2(a) === json2(b), finite2 = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0, CampaignJournalError2;
var init_campaign_journal = __esm(() => {
  init_campaign_contract();
  init_benchmark_provider();
  MAX_LINE2 = 64 * 1024;
  MAX_REQUEST2 = 4 * 1024 * 1024;
  MAX_RESPONSE2 = 64 * 1024 * 1024;
  MAX_JOURNAL2 = 2 * 1024 * 1024 * 1024;
  WIRE2 = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
  CampaignJournalError2 = class CampaignJournalError2 extends Error {
    code;
    stage;
    constructor(code, stage) {
      super(code + (stage ? ":" + stage : ""));
      this.name = "CampaignJournalError";
      this.code = code;
      this.stage = stage;
    }
  };
});

// scripts/benchmark-repair/cny-cash-shadow-v2.ts
import { closeSync as closeSync6, existsSync as existsSync4, fsyncSync as fsyncSync5, openSync as openSync6, readFileSync as readFileSync5, readSync as readSync4, statSync as statSync5, writeFileSync as writeFileSync3, writeSync as writeSync3 } from "fs";
import { join as join7, resolve as resolve7 } from "path";

class CashWriter {
  directory;
  hook;
  path;
  configPin;
  fd;
  prefix;
  failed = false;
  closed = false;
  constructor(directory, config, hook) {
    this.directory = directory;
    this.hook = hook;
    const path = join7(directory, "cash-config.json"), raw = Buffer.from(JSON.stringify(config) + `
`), fd = openSync6(path, "wx", 384);
    try {
      writeFileSync3(fd, raw);
      fsyncSync5(fd);
    } finally {
      closeSync6(fd);
    }
    demand(readFileSync5(path).equals(raw), "cash_config_readback");
    this.configPin = actualPin(path);
    this.path = join7(directory, "cash-events.jsonl");
    this.fd = openSync6(this.path, "wx+", 384);
    fsyncSync5(this.fd);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configPin.sha256 };
  }
  append(kind, data) {
    demand(!this.failed && !this.closed, "cash_writer_unclosed_fault");
    const event = { protocol: "cny-shadow-event-v2", eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, data }, raw = Buffer.from(JSON.stringify(event) + `
`);
    demand(raw.length <= 65536 && this.prefix.bytes + raw.length <= 256 * 1024 ** 2, "cash_metadata_bound");
    const offset = this.prefix.bytes;
    try {
      this.hook?.("cash_write");
      let n = 0;
      while (n < raw.length) {
        const got = writeSync3(this.fd, raw, n, raw.length - n, offset + n);
        demand(got > 0, "cash_short_write");
        n += got;
      }
      this.hook?.("cash_fsync");
      fsyncSync5(this.fd);
      this.hook?.("cash_readback");
      const read = Buffer.alloc(raw.length);
      demand(readSync4(this.fd, read, 0, read.length, offset) === read.length && read.equals(raw) && statSync5(this.path).size === offset + raw.length, "cash_event_readback");
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash(raw) };
      return { ...this.prefix };
    } catch (error) {
      this.failed = true;
      throw error;
    }
  }
  snapshot() {
    return { ...this.prefix };
  }
  fault() {
    return this.failed;
  }
  close() {
    if (this.closed)
      return;
    try {
      fsyncSync5(this.fd);
    } finally {
      closeSync6(this.fd);
      this.closed = true;
    }
  }
}
function createCnyCashShadow(options) {
  return new CnyCashShadow(options);
}

class CnyCashShadow {
  options;
  directory;
  writer;
  binding;
  clock;
  states = new Map;
  ticketStates = new WeakMap;
  poisonReason;
  clockWall;
  clockMono;
  closedPin;
  nextSeq = 0;
  prices;
  config;
  configPin;
  constructor(given) {
    const options = Object.freeze({ ...given, prices: Object.freeze({ ...given.prices }), journal: Object.freeze({ ...given.journal, configPin: Object.freeze({ ...given.journal.configPin }), sourcePin: Object.freeze({ ...given.journal.sourcePin }) }) });
    this.options = options;
    demand(options.providerKind === "local-mock" || options.admission, "real_provider_admission_required");
    demand(options.providerKind !== "local-mock" || !options.admission || options.admission.scope === "f-fixture", "production_admission_cannot_zero_mock");
    if (options.fixtureIo)
      demand(options.admission?.scope === "f-fixture", "cash_fault_hooks_fixture_only");
    this.directory = ordinaryDirectory(options.directory);
    this.clock = options.admission?.clock ?? options.clock ?? REAL_CLOCK;
    this.prices = validatePrices(options.prices);
    this.binding = new JournalBinding(resolve7(options.journal.directory), options.journal.configPin, options.journal.sourcePin);
    demand(this.binding.config.campaign === options.runId, "cash_journal_run_binding");
    this.config = { protocol: "cny-shadow-config-v2", runId: options.runId, providerKind: options.providerKind, scope: options.admission?.scope ?? "local-mock", ownerNonce: options.admission?.owned.ownerNonce ?? null, admissionPin: options.admission?.proofPin ?? null, envelopeNanoCny: (options.admission?.envelopeNanoCny ?? 0n).toString(), carryNanoCny: (options.admission?.carryNanoCny ?? 0n).toString(), pricesPin: options.prices, journalDirectory: resolve7(options.journal.directory), journalConfigPin: options.journal.configPin, journalSourcePin: options.journal.sourcePin, cashSourcePins: [SELF, PROOF_SOURCE], createdAt: new Date(this.clock.wallUnixMs()).toISOString(), priceTTL: "real-beforeForward24h", moneyUnit: "nanoCNY", invoice: false, foreignExchangeConversion: false };
    this.writer = new CashWriter(this.directory, this.config, options.fixtureIo);
    this.configPin = this.writer.configPin;
    try {
      options.admission?.registerCash(this.configPin);
    } catch (error) {
      this.writer.close();
      throw error;
    }
  }
  clockNow() {
    const wall = this.clock.wallUnixMs(), mono = this.clock.monotonicNs();
    const fault = !Number.isFinite(wall) || this.clockWall !== undefined && wall < this.clockWall || this.clockMono !== undefined && mono < this.clockMono;
    if (fault)
      this.poisonReason ??= "clock_rollback_or_unknown";
    this.clockWall = wall;
    this.clockMono = mono;
    return { wall, mono, fault };
  }
  count() {
    let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
    for (const s of this.states.values()) {
      if (s.phase === "known")
        known += s.amount;
      else if (s.phase === "unknown") {
        unknown += s.amount;
        unknownCount++;
      } else if (s.phase === "pending" || s.phase === "denied") {
        pending += s.reservation;
        pendingCount++;
      }
    }
    return { known, pending, unknown, pendingCount, unknownCount };
  }
  snapshot() {
    const t = this.count(), envelope = this.options.admission?.envelopeNanoCny ?? 0n;
    return { protocol: "cny-shadow-cash-v2", runId: this.options.runId, currency: "CNY", providerKind: this.options.providerKind, carriedOriginalUnknownNanoCny: this.config.carryNanoCny, newKnownEstimatedNanoCny: t.known.toString(), newPendingPeakNanoCny: t.pending.toString(), newUnknownPeakNanoCny: t.unknown.toString(), newExposureNanoCny: (t.known + t.pending + t.unknown).toString(), remainingNewEnvelopeNanoCny: (envelope - t.known - t.pending - t.unknown).toString(), pendingCount: t.pendingCount, newUnknownCount: t.unknownCount, poisoned: !!this.poisonReason, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
  }
  beforeForward(input) {
    demand(!this.closedPin && !this.writer.fault(), "cash_closed_or_faulted");
    const j = input.journal.admitted;
    demand(j.admitted === true && integer(j.requestSeq) && j.requestSeq === this.nextSeq && !this.states.has(j.requestSeq), "cash_request_sequence");
    const start = this.binding.start(j.requestSeq, input.journal.startPrefix), raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2), v = requestValues(raw);
    demand(Buffer.from(input.rawRequest).equals(raw) && resolve7(input.capturedRequest.path) === resolve7(j.requestFile) && start.requestFile === j.requestFile && start.requestSha256 === j.requestSha256 && start.requestCompressedSha256 === input.capturedRequest.sha256 && start.requestBytes === raw.length && start.route === input.route && start.providerAttempted === false && Math.abs(start.reservationUsd - j.reservationUsd) < 0.000000001, "cash_actual_admission_binding");
    demand(Math.abs(j.reservationUsd - (v.inputUpper * 0.3 + v.output * 1.2) / 1e6) < 0.000000001, "legacy_usd_reservation_binding");
    const checkpoint = jsonPin(actualPin(join7(this.binding.directory, "api-state.json")));
    demand(checkpoint.configSha256 === this.binding.configSha && !existsSync4(join7(this.binding.directory, "journal-error.json")), "journal_checkpoint_unacknowledged");
    this.binding.consume(checkpoint.durablePrefix);
    for (const path of [j.requestFile, this.binding.path, join7(this.binding.directory, "api-state.json")]) {
      const fd = openSync6(path, "r+");
      try {
        fsyncSync5(fd);
      } finally {
        closeSync6(fd);
      }
    }
    const now = this.clockNow();
    let reason = this.poisonReason;
    try {
      verifyPin(SELF);
      verifyPin(PROOF_SOURCE);
      verifyPin(this.options.prices);
      this.options.admission?.validateForwardSource();
    } catch {
      reason ??= "cash_owner_or_source_or_price_expired";
    }
    if (now.fault)
      reason ??= "cash_clock_fault";
    if (!Number.isFinite(Date.parse(start.startedAt)) || now.wall < Date.parse(start.startedAt))
      reason ??= "cash_start_clock_invalid";
    if (this.options.providerKind === "real-provider" && (!Number.isFinite(Date.parse(this.prices.observedAtUtc)) || now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc)))
      reason ??= "price_expired_or_clock_invalid";
    const r = this.options.providerKind === "local-mock" ? 0n : v.peakNano, t = this.count();
    if (t.known + t.pending + t.unknown + r > (this.options.admission?.envelopeNanoCny ?? 0n))
      reason ??= "cash_envelope_exhausted";
    const ticket = Object.freeze({ id: input.id, requestSeq: j.requestSeq, route: input.route, dispatchAllowed: !reason, peakReservationNanoCny: r.toString() });
    const state = { id: input.id, seq: j.requestSeq, route: input.route, start, reservation: reason ? 0n : r, phase: reason ? "denied" : "pending", amount: 0n, ticket };
    try {
      this.writer.append("start", { id: input.id, requestSeq: j.requestSeq, route: input.route, requestPin: input.capturedRequest, rawRequestSha256: j.requestSha256, startPrefix: input.journal.startPrefix, inputUpper: v.inputUpper, outputLimit: v.output, peakReservationNanoCny: r.toString(), reservedNanoCny: state.reservation.toString(), dispatchAllowed: !reason, reason: reason ?? null, hostWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString() });
    } catch (error) {
      this.poisonReason ??= "cash_admission_persistence_failed";
      throw error;
    }
    this.nextSeq++;
    this.states.set(j.requestSeq, state);
    this.ticketStates.set(ticket, state);
    if (reason)
      this.poisonReason ??= reason;
    return { admitted: !reason, ticket, ...reason ? { reason } : {} };
  }
  poison(reason) {
    demand(reason.length > 0 && reason.length <= 1024, "poison_reason");
    this.poisonReason ??= reason;
    if (!this.writer.fault())
      this.writer.append("poison", { reason });
    return this.snapshot();
  }
  finish(ticket, input) {
    try {
      return this.finishInternal(ticket, input);
    } catch (error) {
      this.poisonReason ??= "cash_finish_validation_failed";
      if (!this.writer.fault() && !this.closedPin)
        this.writer.append("poison", { reason: this.poisonReason, requestSeq: ticket.requestSeq });
      throw error;
    }
  }
  finishInternal(ticket, input) {
    demand(!this.closedPin, "cash_already_closed");
    const s = this.ticketStates.get(ticket);
    demand(s && s.seq === ticket.requestSeq && s.ticket === ticket, "cash_ticket_identity");
    const now = this.clockNow();
    let record, signature, source, unknown = false;
    if (input.kind === "journal-finish") {
      record = this.binding.finish(s.seq, input.journalRef);
      demand(record.requestSha256 === s.start.requestSha256 && record.requestFile === s.start.requestFile && record.route === s.route, "cash_finish_start_binding");
      signature = input.journalRef.finishLineSha256;
      source = { kind: "journal-finish", journalRef: input.journalRef };
    } else {
      demand(input.requestSeq === s.seq && input.evidence.files.length > 0, "failed_capture_binding");
      for (const p of input.evidence.files)
        verifyPin(p);
      this.binding.consume(input.evidence.originalPrefix);
      record = { ...s.start, ...input.evidence };
      signature = hash(JSON.stringify(input.evidence));
      source = { kind: "failed-capture", evidence: input.evidence };
      unknown = true;
      this.poisonReason ??= "source_journal_poisoned_capture";
    }
    if (s.finishSignature === signature)
      return this.snapshot();
    try {
      this.options.admission?.assertOwned();
    } catch {
      this.poisonReason ??= "cash_owner_lost";
    }
    let amount = s.reservation, observedUsage, estimate, responsePin, rawResponseSha;
    if (record.providerAttempted === false && record.confirmedNoForward === true && input.kind === "journal-finish")
      amount = 0n;
    else {
      if (!ticket.dispatchAllowed)
        this.poisonReason ??= "provider_forward_after_cash_denial";
      try {
        responsePin = input.kind === "journal-finish" && record.responseFile ? { path: record.responseFile, sha256: record.responseCompressedSha256 } : input.kind === "failed-capture" ? input.evidence.responsePin : undefined;
        rawResponseSha = input.kind === "journal-finish" ? record.responseSha256 : input.evidence.rawResponseSha256;
        demand(responsePin && rawResponseSha, "complete_response_missing");
        const raw = gzipProof(responsePin, rawResponseSha), data2 = JSON.parse(raw.toString("utf8"));
        observedUsage = data2.usage;
        demand(same(data2.usage, record.usage) && data2.model === record.servedModel || input.kind === "failed-capture" && same(data2.usage, input.evidence.usage), "response_usage_binding");
        const window = peakWindow(Date.parse(s.start.startedAt), now.wall), expired = now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc);
        const peak = window.peak || window.clockFault || now.fault || expired;
        estimate = this.options.providerKind === "local-mock" ? 0n : pricedUsage(observedUsage, peak);
        amount = estimate;
        if (input.kind === "journal-finish" && (record.httpStatus !== 200 || record.fault || record.completionValid !== true)) {
          unknown = true;
          this.poisonReason ??= "provider_body_or_completion_not_complete";
        }
        if (window.clockFault || now.fault || expired) {
          unknown = true;
          this.poisonReason ??= "clock_or_price_unknown_at_capture";
        }
      } catch {
        unknown = true;
        this.poisonReason ??= "missing_or_invalid_complete_usage";
      }
    }
    if (input.kind === "failed-capture" && s.phase === "known" && responsePin && observedUsage && estimate === s.amount && rawResponseSha && rawResponseSha === s.lastResponseRawSha) {
      this.writer.append("late-evidence", { id: s.id, requestSeq: s.seq, source, responsePin, rawResponseSha256: rawResponseSha, observedUsage, amountNanoCny: s.amount.toString(), reason: "overlapping_known_finish_retained_once" });
      return this.snapshot();
    }
    if (input.kind === "failed-capture")
      unknown = true;
    if (s.phase === "unknown" || s.phase === "known" && s.finishSignature) {
      unknown = true;
      this.poisonReason ??= "conflicting_or_late_cash_finish";
    }
    if (unknown)
      amount = [s.reservation, s.amount, estimate ?? 0n].reduce((a, b) => a > b ? a : b);
    const phase = unknown ? "unknown" : "known";
    const data = { id: s.id, requestSeq: s.seq, phase, amountNanoCny: amount.toString(), peakReservationNanoCny: s.reservation.toString(), source, signature, responsePin: responsePin ?? null, rawResponseSha256: rawResponseSha ?? null, observedUsage: observedUsage ?? null, observedEstimatedNanoCny: estimate?.toString() ?? null, hostCaptureWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString(), clockFault: now.fault, poisonReason: this.poisonReason ?? null };
    try {
      this.writer.append("finish", data);
    } catch (error) {
      this.poisonReason ??= "cash_finish_persistence_failed";
      throw error;
    }
    s.phase = phase;
    s.amount = amount;
    s.finishSignature = signature;
    s.lastResponseRawSha = rawResponseSha;
    if (amount > s.reservation && record.providerAttempted !== false)
      this.poisonReason ??= "actual_estimate_exceeds_reservation";
    if (BigInt(this.snapshot().newExposureNanoCny) > (this.options.admission?.envelopeNanoCny ?? 0n))
      this.poisonReason ??= "actual_estimate_exceeds_envelope";
    return this.snapshot();
  }
  close() {
    if (this.closedPin)
      return this.closedPin;
    const inspection = inspectCampaignJournal2(this.options.journal.directory), snapshot = this.snapshot();
    const cashPrefix = this.writer.snapshot();
    let good = !this.writer.fault() && inspection.valid && inspection.accountingClosed && snapshot.pendingCount === 0 && snapshot.newUnknownCount === 0;
    try {
      this.options.admission?.assertOwned();
    } catch {
      good = false;
    }
    this.writer.close();
    const cashEvents = actualPin(this.writer.path);
    const value = { protocol: "cny-shadow-close-v2", runId: this.options.runId, ownerNonce: this.config.ownerNonce, configPin: this.configPin, cashEventsPin: cashEvents, cashPrefix, journalConfigPin: this.options.journal.configPin, journalSourcePin: this.options.journal.sourcePin, journalDirectory: resolve7(this.options.journal.directory), journalPrefix: inspection.prefix ?? this.binding.current(), journalValid: inspection.valid, journalAccountingClosed: inspection.accountingClosed, snapshot, releasePermitted: good, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
    const path = join7(this.directory, "cash-close.json"), fd = openSync6(path, "wx", 384);
    try {
      writeFileSync3(fd, JSON.stringify(value, null, 2) + `
`);
      fsyncSync5(fd);
    } finally {
      closeSync6(fd);
    }
    this.closedPin = actualPin(path);
    if (good)
      verifyCashClosure(this.closedPin);
    return this.closedPin;
  }
}
function verifyCashClosure(pin) {
  const proof = jsonPin(pin), config = jsonPin(proof.configPin);
  demand(proof.protocol === "cny-shadow-close-v2" && config.protocol === "cny-shadow-config-v2" && proof.runId === config.runId && proof.ownerNonce === config.ownerNonce, "cash_close_config");
  demand(config.providerKind === "real-provider" || config.providerKind === "local-mock", "cash_provider_kind");
  for (const p of config.cashSourcePins)
    verifyPin(p);
  const prices = validatePrices(config.pricesPin);
  verifyPin(proof.cashEventsPin);
  verifyPin(config.journalSourcePin);
  if (config.admissionPin) {
    const admission = jsonPin(config.admissionPin);
    demand(admission.protocol === "paid-resource-admission-v2" && admission.runId === config.runId && admission.owned.ownerNonce === config.ownerNonce && admission.selectedNewEnvelopeNanoCny === config.envelopeNanoCny && admission.carryNanoCny === config.carryNanoCny, "cash_admission_config_binding");
  }
  const binding = new JournalBinding(config.journalDirectory, config.journalConfigPin, config.journalSourcePin), raw = readFileSync5(proof.cashEventsPin.path);
  let at = 0, seq = 0, last = proof.configPin.sha256;
  const states = new Map;
  for (const lineText of raw.toString("utf8").split(`
`)) {
    if (!lineText)
      continue;
    const line = Buffer.from(lineText + `
`), e = JSON.parse(lineText);
    demand(Buffer.from(JSON.stringify(e) + `
`).equals(line) && e.protocol === "cny-shadow-event-v2" && e.eventSeq === seq && e.previousEventSha256 === last, "cash_event_chain");
    const d = e.data;
    if (e.kind === "start") {
      demand(!states.has(d.requestSeq) && d.requestSeq === states.size, "cash_start_sequence");
      const start = binding.start(d.requestSeq, d.startPrefix), body = gzipProof(d.requestPin, d.rawRequestSha256, undefined, 4 * 1024 ** 2), v = requestValues(body);
      demand(start.requestSha256 === d.rawRequestSha256 && start.requestCompressedSha256 === d.requestPin.sha256 && resolve7(start.requestFile) === resolve7(d.requestPin.path) && start.requestBytes === body.length && start.route === d.route && v.inputUpper === d.inputUpper && v.output === d.outputLimit, "cash_start_proof");
      const r = config.providerKind === "local-mock" ? 0n : v.peakNano;
      demand(typeof d.dispatchAllowed === "boolean" && r.toString() === d.peakReservationNanoCny && d.reservedNanoCny === (d.dispatchAllowed ? r : 0n).toString(), "cash_peak_reservation");
      states.set(d.requestSeq, { phase: d.dispatchAllowed ? "pending" : "denied", amount: 0n, reservation: BigInt(d.reservedNanoCny), start });
    } else if (e.kind === "finish") {
      const s = states.get(d.requestSeq);
      demand(s, "cash_finish_unknown");
      let min = 0n;
      if (d.source.kind === "journal-finish") {
        const receipt = binding.finish(d.requestSeq, d.source.journalRef);
        demand(d.signature === d.source.journalRef.finishLineSha256 && receipt.requestSha256 === s.start.requestSha256, "cash_finish_member");
        if (!(receipt.providerAttempted === false && receipt.confirmedNoForward === true)) {
          if (receipt.httpStatus !== 200 || receipt.fault || receipt.completionValid !== true)
            demand(d.phase === "unknown", "incomplete_provider_receipt_settled");
          demand(d.responsePin && d.rawResponseSha256 && resolve7(d.responsePin.path) === resolve7(receipt.responseFile) && d.responsePin.sha256 === receipt.responseCompressedSha256 && d.rawResponseSha256 === receipt.responseSha256, "cash_known_response_missing");
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand(same(data.usage, d.observedUsage) && same(data.usage, receipt.usage) && data.model === receipt.servedModel, "cash_usage_proof");
          const window = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs), expired = !Number.isFinite(Date.parse(prices.observedAtUtc)) || d.hostCaptureWallUnixMs - Date.parse(prices.observedAtUtc) > 24 * 3600000 || d.hostCaptureWallUnixMs < Date.parse(prices.observedAtUtc);
          if (window.clockFault || d.clockFault || expired)
            demand(d.phase === "unknown", "cash_clock_unknown_settled");
          try {
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, window.peak || window.clockFault || d.clockFault || expired);
          } catch {
            demand(d.phase === "unknown", "invalid_usage_settled");
            min = s.reservation;
          }
        }
      } else {
        demand(d.source.kind === "failed-capture" && d.phase === "unknown", "failed_capture_settled");
        for (const p of d.source.evidence.files)
          verifyPin(p);
        min = s.reservation;
        if (d.responsePin && d.rawResponseSha256) {
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand(same(data.usage, d.observedUsage), "late_usage_proof");
          try {
            const w = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs);
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, w.peak || d.clockFault);
          } catch {}
        }
      }
      if (s.phase === "unknown")
        demand(d.phase === "unknown", "sealed_unknown_reopened");
      if (d.phase === "unknown")
        min = [min, s.reservation, s.amount].reduce((a, b) => a > b ? a : b);
      demand((d.phase === "known" || d.phase === "unknown") && BigInt(d.amountNanoCny) >= min && (d.phase !== "known" || BigInt(d.amountNanoCny) === min), "cash_cost_replay");
      s.phase = d.phase;
      s.amount = BigInt(d.amountNanoCny);
      s.signature = d.signature;
      s.rawSha = d.rawResponseSha256;
    } else if (e.kind === "late-evidence") {
      const s = states.get(d.requestSeq);
      demand(s && s.phase === "known" && s.rawSha === d.rawResponseSha256 && d.source.kind === "failed-capture" && BigInt(d.amountNanoCny) === s.amount, "late_overlap_binding");
      for (const p of d.source.evidence.files)
        verifyPin(p);
      const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
      demand(same(data.usage, d.observedUsage), "late_overlap_usage");
    } else
      demand(e.kind === "poison", "cash_event_kind");
    at += line.length;
    seq++;
    last = hash(line);
  }
  demand(at === raw.length && same(proof.cashPrefix, { bytes: at, eventCount: seq, lastSha256: last }), "cash_exact_prefix");
  let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
  for (const s of states.values()) {
    if (s.phase === "known")
      known += s.amount;
    else if (s.phase === "unknown") {
      unknown += s.amount;
      unknownCount++;
    } else {
      pending += s.reservation;
      pendingCount++;
    }
  }
  const exposure = known + pending + unknown;
  demand(proof.snapshot.protocol === "cny-shadow-cash-v2" && proof.snapshot.runId === config.runId && proof.snapshot.currency === "CNY" && proof.snapshot.providerKind === config.providerKind && proof.snapshot.carriedOriginalUnknownNanoCny === config.carryNanoCny && proof.snapshot.newKnownEstimatedNanoCny === known.toString() && proof.snapshot.newPendingPeakNanoCny === pending.toString() && proof.snapshot.newUnknownPeakNanoCny === unknown.toString() && proof.snapshot.newExposureNanoCny === exposure.toString() && proof.snapshot.remainingNewEnvelopeNanoCny === (BigInt(config.envelopeNanoCny) - exposure).toString() && proof.snapshot.pendingCount === pendingCount && proof.snapshot.newUnknownCount === unknownCount && proof.snapshot.invoice === false && proof.snapshot.foreignExchangeConversion === false, "cash_snapshot_replay");
  const journal = inspectCampaignJournal2(config.journalDirectory);
  demand(journal.valid && journal.accountingClosed && journal.snapshot?.acceptedRequestCount === states.size && same(journal.prefix, proof.journalPrefix) && pendingCount === 0 && unknownCount === 0 && proof.releasePermitted === true, "cash_or_peer_not_closed");
  return { proof, config, states };
}
var SELF, PROOF_SOURCE;
var init_cny_cash_shadow_v2 = __esm(() => {
  init_campaign_journal();
  init_paid_resource_proof_v2();
  SELF = actualPin(import.meta.path);
  PROOF_SOURCE = actualPin(join7(import.meta.dir, "paid-resource-proof-v2.ts"));
});

// app/src/install/tables.json
var init_tables = () => {};

// app/src/install/index.ts
function ident(s, what) {
  if (!IDENT.test(s))
    throw new Error(`illegal ${what}: ${s}`);
  return s;
}
function tableNameOf(pattern, value) {
  const safe = value.replace(/[^A-Za-z0-9_]/g, "_");
  const name = pattern.replace("{}", safe);
  return ident(name, "grown table name");
}
var IDENT;
var init_install = __esm(() => {
  init_db();
  init_tables();
  IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
});

// app/src/msg/deliver.ts
var HUMAN_MARK = "[human] ", HUMAN, FROM, HUMAN_KINDS, ROLES, KINDS;
var init_deliver = __esm(() => {
  init_db();
  init_install();
  HUMAN = new Set(["user", "voice"]);
  FROM = {
    user: { kind: "user", role: "user" },
    voice: { kind: "voice", role: "user" },
    world: { kind: "inject", role: "user" },
    skill: { kind: "skill", role: "skill" },
    tool: { kind: "tool", role: "tool" },
    agent: { kind: "prompt", role: "assistant" },
    kernel: { kind: "inject", role: "system" }
  };
  HUMAN_KINDS = new Set([...HUMAN].map((b) => FROM[b].kind));
  ROLES = [...new Set(Object.values(FROM).map((f) => f.role))].sort();
  KINDS = [
    ["user", "Written by a person. Prefixed with " + HUMAN_MARK + " on the way out so it stays distinguishable from system injections"],
    ["voice", "Spoken by a person, transcribed from the realtime lane. Its role is also user; only kind tells speech apart from typing"],
    ["inject", "Injected by the system. Also goes out as role=user; only kind tells it apart"],
    ["skill", "A prompt placed by a skill"],
    ["tool", "A tool result"],
    ["prompt", "What the model itself said"],
    ["call", "The model requesting tools; the calls ride in body. Something still has to run these"],
    [
      "graded",
      "A call the system wrote down after the fact, not one the model asked for - an outside judgement, shaped like a call so the model can read it. Nothing runs these: they arrive with their result already attached"
    ],
    ["intervene", "A mark left by a user intervening while it runs"]
  ];
});

// app/src/objective/store.ts
var CANDIDATE;
var init_store = __esm(() => {
  init_spec();
  CANDIDATE = {
    type: "object",
    properties: {
      answer: {
        type: "string",
        description: "The answer, verbatim (keep the \\boxed{} if the task asks for one). This exact text is what gets " + "graded, not your derivation."
      }
    },
    required: ["answer"]
  };
});

// app/src/tree/dfs.ts
var DEAD, SUBMIT = "submit", SUBMIT_TOOL;
var init_dfs = __esm(() => {
  init_db();
  init_deliver();
  init_install();
  init_run();
  init_store();
  DEAD = new Set(["dead_failed", "dead_below_bar"]);
  SUBMIT_TOOL = {
    name: SUBMIT,
    does: "Hand the work in: the answer passed here is what gets graded, exactly as written. Text that is not " + "passed here is not read as an answer.",
    params: CANDIDATE,
    output: { type: "object", properties: { handingIn: { type: "boolean" } } },
    prompt: "At the hand-in step no other tool is attached. The hand-in step is reached on its own once the working " + "budget runs out.",
    expectMs: 1e4
  };
});

// app/src/objective/candidate.ts
function finalCandidate(db, task) {
  const row = all(db, "select mode,created_at,solve_seconds from task where id = ?", [task])[0];
  if (!row?.mode)
    return;
  const limit = Number(row.solve_seconds);
  const deadline = Number.isFinite(limit) && limit > 0 ? Number(row.created_at) + limit * 1000 : Number.MAX_SAFE_INTEGER;
  const sub = tableNameOf("task_{}", String(row.mode));
  const units = all(db, `select agent,instance,unit from "${sub}" where task = ? order by unit desc`, [task]);
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const calls = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'call' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    for (const call of calls) {
      try {
        const payload = JSON.parse(String(call.body));
        for (const item of [...payload.calls ?? []].reverse()) {
          if (item.name === SUBMIT)
            return { body: typeof item.input?.answer === "string" ? item.input.answer : "", how: "submitted" };
        }
      } catch {}
    }
  }
  if (all(db, "select 1 from cycle where mode = ? and cycle = ? limit 1", [row.mode, SUBMIT]).length)
    return;
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const prompts = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'prompt' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    const said = prompts.find((message) => String(message.body ?? "").trim());
    if (said)
      return { body: String(said.body), how: "last words" };
  }
  return;
}
var init_candidate = __esm(() => {
  init_db();
  init_install();
  init_dfs();
});

// scripts/benchmark-repair/scientific-startup-proof.ts
import { basename as basename3, dirname as dirname4, join as join16, resolve as resolve13 } from "path";
var ROOT, ZERO_STARTUP_RUN = "repair-2026-10-08T17-36-10-873Z", archive, proofHome, oldSources;
var init_scientific_startup_proof = __esm(async () => {
  init_paid_resource_proof_v2();
  init_scientific_journal_plan();
  init_registry();
  ROOT = resolve13(import.meta.dir, "../..");
  archive = join16(ROOT, "docs/repair-2026-10-08/scientific-startup-failures", ZERO_STARTUP_RUN, "root-frozen-v1");
  proofHome = join16(ROOT, "docs/repair-2026-10-08/scientific-startup-aborts", ZERO_STARTUP_RUN);
  oldSources = new Map([
    ["scientific-journal-campaign.ts", "458993f378a35c55f65be54c48cbc4d70b277eada87a7d65baf6edcf8eefc493"],
    ["paid-resource-admission-v2.ts", "859844a7f32f88f6fc51b9d0b468620c1ac6222cea9996c7340e3d6f303a9828"],
    ["scientific-journal-admission.ts", "d619371ff2a8763f738a84377bf97d4da20c213654982fd41c7553ed6a2d579d"]
  ]);
  if (false) {}
});

// scripts/benchmark-repair/paid-resource-admission-v2.ts
import { basename as basename4, join as join17, resolve as resolve14 } from "path";
var MODULE_ROOT, SELF2, INTRINSIC_SOURCES;
var init_paid_resource_admission_v2 = __esm(async () => {
  init_campaign_contract();
  init_paid_resource_proof_v2();
  init_cny_cash_shadow_v2();
  init_cny_cash_shadow_v2();
  await init_scientific_startup_proof();
  MODULE_ROOT = resolve14(import.meta.dir, "../..");
  SELF2 = actualPin(import.meta.path);
  INTRINSIC_SOURCES = [SELF2, actualPin(join17(import.meta.dir, "paid-resource-proof-v2.ts")), actualPin(join17(import.meta.dir, "campaign-contract.ts"))];
});

// scripts/benchmark-repair/skb-jpg-contract.ts
var init_skb_jpg_contract = __esm(() => {
  init_campaign_contract();
});

// scripts/benchmark-repair/jpg-journal-contract.ts
var JPG_EXECUTION_FILES;
var init_jpg_journal_contract = __esm(() => {
  init_paid_resource_proof_v2();
  init_skb_jpg_contract();
  JPG_EXECUTION_FILES = [
    "skb-jpg-journal-campaign.ts",
    "jpg-paid-resource-admission-v1.ts",
    "audit-jpg-journal-campaign.py",
    "jpg-journal-contract.ts",
    "campaign-journal.ts",
    "scientific-journal-proxy.ts",
    "campaign-contract.ts",
    "audit-journal-canonical.ts",
    "cny-cash-shadow-v2.ts",
    "paid-resource-proof-v2.ts",
    "paid-resource-admission-v2.ts",
    "scientific-startup-proof.ts",
    "scientific-journal-plan.ts",
    "skb-jpg-contract.ts",
    "skb-jpg-stand.py",
    "skb-jpg-host-ops.py",
    "skb-jpg-audit.ts",
    "skb-jpg-native-python.ts",
    "skb-jpg-native-bootstrap.py",
    "skb-jpg-native-python.json",
    "software-jpg-private-grader.py",
    "software-jpg-build.py",
    "tb-engine.ts",
    "tb-tool-gateway.ts",
    "tb-nginx-contract.ts"
  ].map((name) => `scripts/benchmark-repair/${name}`);
});

// scripts/benchmark-repair/jpg-paid-resource-admission-v1.ts
import { basename as basename5, dirname as dirname5, join as join18, resolve as resolve15 } from "path";
var ROOT2, SELF3;
var init_jpg_paid_resource_admission_v1 = __esm(async () => {
  init_cny_cash_shadow_v2();
  init_paid_resource_proof_v2();
  init_jpg_journal_contract();
  await init_paid_resource_admission_v2();
  ROOT2 = resolve15(import.meta.dir, "../..");
  SELF3 = actualPin(import.meta.path);
});

// scripts/benchmark-repair/jpg-d-storage-profile.ts
var init_jpg_d_storage_profile = __esm(() => {
  init_paid_resource_proof_v2();
});

// scripts/benchmark-repair/jpg-D-journal-contract.ts
import { join as join19, resolve as resolve16 } from "path";
var JPG_D_EXECUTION_NAMES, JPG_D_EXECUTION_FILES, ROOT3;
var init_jpg_D_journal_contract = __esm(() => {
  init_paid_resource_proof_v2();
  init_jpg_journal_contract();
  init_jpg_d_storage_profile();
  init_skb_jpg_contract();
  JPG_D_EXECUTION_NAMES = [
    "skb-jpg-D-journal-campaign.ts",
    "jpg-D-paid-resource-admission-v1.ts",
    "audit-jpg-D-journal-campaign.py",
    "jpg-D-journal-contract.ts",
    "jpg-D-native-service-v1.ts",
    "jpg-D-stand-v1.py",
    "jpg-D-store-init-v1.py",
    "jpg-D-grade-parent-v1.py",
    "jpg-d-storage-profile.ts",
    "jpg_d_storage_profile.py",
    "jpg_private_ram_profile.py",
    "jpg_private_ram_executor.py",
    "financial-interruption-closure-v1.ts",
    "jpg-financial-abort-scanner-v1.ts",
    "financial-interruption-release.ts"
  ];
  JPG_D_EXECUTION_FILES = [...JPG_EXECUTION_FILES, ...JPG_D_EXECUTION_NAMES.map((n) => "scripts/benchmark-repair/" + n)];
  ROOT3 = resolve16(import.meta.dir, "../..");
});

// scripts/benchmark-repair/audit-scientific-financial-interruption.ts
import { closeSync as closeSync10, existsSync as existsSync6, fsyncSync as fsyncSync9, lstatSync as lstatSync4, mkdirSync as mkdirSync8, openSync as openSync10, readFileSync as readFileSync13, readSync as readSync7, readdirSync as readdirSync4, realpathSync as realpathSync4, statSync as statSync8, writeSync as writeSync6 } from "fs";
import { basename as basename6, dirname as dirname6, join as join20, resolve as resolve17 } from "path";
import { gzipSync as gzipSync4 } from "zlib";

class EvidenceWriter {
  path;
  fd;
  batch = [];
  bytes = 0;
  rows = 0;
  chain = SELF4.sha256;
  closed = false;
  constructor(out) {
    this.path = join20(out, "request-evidence.jsonl.gz");
    this.fd = openSync10(this.path, "wx", 384);
  }
  append(row) {
    const payload = JSON.stringify(row), entry = { previousRowSha256: this.chain, ...row };
    this.chain = hash(JSON.stringify(entry) + `
`);
    this.batch.push(JSON.stringify(entry) + `
`);
    this.rows++;
    if (this.batch.length >= 64)
      this.flush();
  }
  flush() {
    if (!this.batch.length)
      return;
    const b = gzipSync4(Buffer.from(this.batch.join("")));
    demand(this.bytes + b.length <= 8 * 1024 ** 2, "new_evidence_8MiB_bound");
    let n = 0;
    while (n < b.length) {
      const m = writeSync6(this.fd, b, n, b.length - n, this.bytes + n);
      demand(m > 0, "new_evidence_short_write");
      n += m;
    }
    this.bytes += b.length;
    this.batch = [];
  }
  close() {
    this.flush();
    fsyncSync9(this.fd);
    closeSync10(this.fd);
    this.closed = true;
    return { pin: actualPin(this.path), rows: this.rows, lastRowSha256: this.chain, concatenatedGzipMembers: true };
  }
  abort() {
    if (this.closed)
      return;
    try {
      fsyncSync9(this.fd);
    } finally {
      closeSync10(this.fd);
      this.closed = true;
    }
  }
}
var ROOT4, RUN = "repair-2026-10-08T18-32-57-118Z", STORE, META, SELF4, FIRST, CASH_REVIEW, INTRINSIC;
var init_audit_scientific_financial_interruption = __esm(() => {
  init_campaign_journal();
  init_campaign_contract();
  init_paid_resource_proof_v2();
  ROOT4 = resolve17(import.meta.dir, "../..");
  STORE = "D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-" + RUN;
  META = join20(ROOT4, "docs/repair-2026-10-08/campaigns", RUN);
  SELF4 = actualPin(import.meta.path);
  FIRST = { path: join20(ROOT4, "docs/repair-2026-10-08/scientific-interruption-" + RUN, "first-pass.json"), sha256: "204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758" };
  CASH_REVIEW = { path: join20(ROOT4, "docs/repair-2026-10-08/scientific-interruption-" + RUN, "cash-metadata-review.json"), sha256: "796c3870bb7919ed6fa655272b8f955ed100eea38b170e6680fb587a8352107a" };
  INTRINSIC = [{ path: join20(import.meta.dir, "paid-resource-admission-v2.ts"), bytes: 41347, sha256: "0b752576bd37235140a7b97dafee16741ebaadd9cafda3370e20317d9fdddb0e" }, { path: join20(import.meta.dir, "paid-resource-proof-v2.ts"), bytes: 10106, sha256: "b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe" }, { path: join20(import.meta.dir, "campaign-contract.ts"), bytes: 11488, sha256: "8ddbc1428a470ca18e5f6605f2bb48eccabc1bb5140ac777879601e4aec66305" }];
  if (false) {}
});

// scripts/benchmark-repair/financial-interruption-release.ts
import { basename as basename7, dirname as dirname7, join as join21, resolve as resolve18 } from "path";
var FINANCIAL_RUN = "repair-2026-10-08T18-32-57-118Z", ROOT5, META2, STORE2, SELF5, REPORT, INDEX, AUDITOR, FIRST2, LOCK, REGISTRY, PROOF, SNAPSHOT_SOURCE, SNAPSHOT_REVIEW, SNAPSHOT_RECEIPT, OWNER, OUTPUT_ROOT, FIXTURE_ROOT;
var init_financial_interruption_release = __esm(async () => {
  init_paid_resource_proof_v2();
  init_audit_scientific_financial_interruption();
  ROOT5 = resolve18(import.meta.dir, "../..");
  META2 = join21(ROOT5, "docs/repair-2026-10-08/campaigns", FINANCIAL_RUN);
  STORE2 = resolve18("D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-" + FINANCIAL_RUN);
  SELF5 = actualPin(import.meta.path);
  REPORT = { path: join21(ROOT5, "docs/repair-2026-10-08/scientific-financial-interruptions", FINANCIAL_RUN + "-audit-v2/audit.json"), bytes: 10661, sha256: "4722f1e9d25ed2f2ed061cf6d37fa89d4c5816625f15809b8309cccfdbcbc4d4" };
  INDEX = { path: join21(dirname7(REPORT.path), "request-evidence.jsonl.gz"), bytes: 6693036, sha256: "cc1b832b6f59001de8bf3ba4a2d31e7a0dcdeb704f276e1f55bfb4ec9c4f956e" };
  AUDITOR = { path: join21(import.meta.dir, "audit-scientific-financial-interruption.ts"), bytes: 24818, sha256: "58686eaecd47e1f86c89eef544ad72966afc2abf420b5fccca2706fb9c35d244" };
  FIRST2 = { path: join21(ROOT5, "docs/repair-2026-10-08/scientific-interruption-" + FINANCIAL_RUN, "first-pass.json"), bytes: 35517, sha256: "204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758" };
  LOCK = { path: join21(ROOT5, ".phase1-data/owned-paid-campaign.lock.json"), bytes: 432, sha256: "31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53" };
  REGISTRY = { path: join21(META2, "paid-resource-v2-run.json"), bytes: 393, sha256: "b635eef60fd169d6133c39f5bcfd4f0f50d3d46b00d26723f7f08e6ce8c47d8a" };
  PROOF = { path: join21(import.meta.dir, "paid-resource-proof-v2.ts"), bytes: 10106, sha256: "b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe" };
  SNAPSHOT_SOURCE = { path: join21(import.meta.dir, "science-worker-db-snapshot-v1.py"), bytes: 20986, sha256: "3d3c408fa18cc76569f841bf3af68366fb68d4adcb167781a7b030dd65573d32" };
  SNAPSHOT_REVIEW = { path: join21(ROOT5, "test/fixtures/repair/science-db-snapshot-native-controls-v1/review.json"), sha256: "c382728966b8ecae1c2e934dd22404ee40483948e9d6c10f24125003870a574e" };
  SNAPSHOT_RECEIPT = { path: join21(ROOT5, "test/fixtures/repair/science-db-snapshots/root-snapshot-2026-10-09T04-10-v1.json"), bytes: 43523, sha256: "8134c6e96ef8718615da901548f2c0c6ada7076ee15543c4723c555ba2a36220" };
  OWNER = { pid: 104376, startedAt: "2026-10-08T18:35:52.317Z", runId: FINANCIAL_RUN, entry: join21(import.meta.dir, "scientific-journal-campaign.ts"), ownerNonce: "a324165d98aa2edcca6aee98d1ef2099ba6defaac020e4c4", mode: "carry-science-oom-2026-10-08-v2", policyFaultSha256: "b56760e02fc14725c7fede86457f6155cb3aa4fdeefa9001b2248282a1cb0357" };
  OUTPUT_ROOT = join21(ROOT5, "docs/repair-2026-10-08/scientific-financial-releases");
  FIXTURE_ROOT = join21(ROOT5, ".scratch/financial-release-controls");
  if (false) {}
});

// scripts/benchmark-repair/financial-interruption-closure-v1.ts
import { dirname as dirname8, join as join22, resolve as resolve19 } from "path";
var ROOT6, META3, STORE3, HOME, ACTUAL_HOME, ACK, INTENT, INSPECTION, LOCK_ARCHIVE, ROOT_REVIEW, REPORT2, INDEX2, SOURCE, REGISTRY2, LOCK2, FIRST3, IDENTITY, ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY;
var init_financial_interruption_closure_v1 = __esm(async () => {
  init_paid_resource_proof_v2();
  await init_financial_interruption_release();
  ROOT6 = resolve19(import.meta.dir, "../..");
  META3 = join22(ROOT6, "docs/repair-2026-10-08/campaigns", FINANCIAL_RUN);
  STORE3 = resolve19("D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-" + FINANCIAL_RUN);
  HOME = join22(ROOT6, "docs/repair-2026-10-08/scientific-financial-releases");
  ACTUAL_HOME = join22(HOME, FINANCIAL_RUN + "-root-v1");
  ACK = { path: join22(ACTUAL_HOME, "release-ack.json"), bytes: 3385, sha256: "948bd64de553bd67809fc9247a33b213889e8cb9333ebbb870b44ec8f7471027" };
  INTENT = { path: join22(ACTUAL_HOME, "release-intent.json"), bytes: 3467, sha256: "1b6c529ae4bacc8d25538db2d3d5c52eade287f46a0e03f1ebbeb132e054c5d3" };
  INSPECTION = { path: join22(ACTUAL_HOME, "inspection.json"), bytes: 3232, sha256: "485c4f2b9cfea712b19d3e5bce8a264fbcb8ecf9328a25a567ecddedbc5ac61c" };
  LOCK_ARCHIVE = { path: join22(ACTUAL_HOME, "root-original-lock-bytes.json"), bytes: 432, sha256: "31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53" };
  ROOT_REVIEW = { path: join22(ACTUAL_HOME, "root-independent-release-review.json"), bytes: 2686, sha256: "bdb3dae453dc20481dfa6c47983010d82fffd5790a284e3ad4ac87c1d0fe9fb5" };
  REPORT2 = { path: join22(ROOT6, "docs/repair-2026-10-08/scientific-financial-interruptions", FINANCIAL_RUN + "-audit-v2/audit.json"), bytes: 10661, sha256: "4722f1e9d25ed2f2ed061cf6d37fa89d4c5816625f15809b8309cccfdbcbc4d4" };
  INDEX2 = { path: join22(dirname8(REPORT2.path), "request-evidence.jsonl.gz"), bytes: 6693036, sha256: "cc1b832b6f59001de8bf3ba4a2d31e7a0dcdeb704f276e1f55bfb4ec9c4f956e" };
  SOURCE = { path: join22(import.meta.dir, "financial-interruption-release.ts"), bytes: 41248, sha256: "4f2f2aad2bcc0857b4cf73120bc48fb70b9632df408ed8f06c6b5ae5dfe2dd41" };
  REGISTRY2 = { path: join22(META3, "paid-resource-v2-run.json"), bytes: 393, sha256: "b635eef60fd169d6133c39f5bcfd4f0f50d3d46b00d26723f7f08e6ce8c47d8a" };
  LOCK2 = { path: join22(ROOT6, ".phase1-data/owned-paid-campaign.lock.json"), bytes: 432, sha256: "31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53" };
  FIRST3 = { path: join22(ROOT6, "docs/repair-2026-10-08/scientific-interruption-" + FINANCIAL_RUN, "first-pass.json"), bytes: 35517, sha256: "204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758" };
  IDENTITY = { path: join22(ROOT6, "test/fixtures/repair/science-db-snapshots/root-proxy-identity-routed-v2/proxy-port-identity.json"), bytes: 9977, sha256: "66f88e99a6d63aa2ab92c4146611d6e5cc11729c03077d629a2b81d629cad1d8" };
  ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY = Object.freeze({ acknowledgementPin: ACK, originalLockArchivePin: LOCK_ARCHIVE });
});

// scripts/benchmark-repair/jpg-financial-abort-scanner-v1.ts
import { join as join23, resolve as resolve20 } from "path";
var ROOT7;
var init_jpg_financial_abort_scanner_v1 = __esm(async () => {
  init_paid_resource_proof_v2();
  await __promiseAll([
    init_paid_resource_admission_v2(),
    init_jpg_paid_resource_admission_v1(),
    init_financial_interruption_release(),
    init_financial_interruption_closure_v1()
  ]);
  ROOT7 = resolve20(import.meta.dir, "../..");
});

// scripts/benchmark-repair/jpg-D-paid-resource-admission-v1.ts
import { basename as basename8, dirname as dirname9, join as join24, resolve as resolve21 } from "path";
var ROOT8, SELF6;
var init_jpg_D_paid_resource_admission_v1 = __esm(async () => {
  init_cny_cash_shadow_v2();
  init_paid_resource_proof_v2();
  init_jpg_D_journal_contract();
  await __promiseAll([
    init_paid_resource_admission_v2(),
    init_jpg_financial_abort_scanner_v1()
  ]);
  ROOT8 = resolve21(import.meta.dir, "../..");
  SELF6 = actualPin(import.meta.path);
});

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/worker.ts
init_paid_resource_proof_v2();
import { readFileSync as readFileSync21, existsSync as existsSync14, mkdirSync as mkdirSync16, writeFileSync as writeFileSync13 } from "fs";
import { resolve as resolve30, join as join35, sep } from "path";
import { randomBytes as randomBytes7 } from "crypto";

// scripts/benchmark-campaign/full-f/terminal-bench/isolated-task-plan-dynamic.next.ts
import { resolve as resolve2 } from "path";
function validateIsolatedJobs(manifest, plan) {
  const check = (ok, code) => {
    if (!ok)
      throw Error(code);
  };
  check(manifest.taskIds.length === 89 && new Set(manifest.taskIds).size === 89, "isolated_full89_required");
  check(plan.protocol === "terminal-isolated-task-plan-v1" && plan.maximumWorkers === 16, "isolated_dynamic_worker_plan_required");
  check(Array.isArray(plan.jobs) && plan.jobs.length > 0, "isolated_jobs_required");
  const ids = new Set, paths = new Set;
  for (const job of plan.jobs) {
    const task = manifest.records.find((t) => t.taskId === job.taskId);
    check(task && !ids.has(job.taskId), "isolated_task_unique_required");
    ids.add(job.taskId);
    const path = resolve2(job.readinessPin.path);
    check(!paths.has(path), "isolated_readiness_unique_required");
    paths.add(path);
    check(job.originalPlannedGrowthBytes === task.officialEnvironment.storage_mb * 1024 ** 2, "isolated_original_storage_required");
    check(job.originalPeakMemoryMb === Math.max(4096, 2 * task.officialEnvironment.memory_mb), "isolated_candidate_and_grader_peak_required");
  }
  return plan.jobs;
}

// scripts/benchmark-campaign/full-f/terminal-bench/isolated-run-directory.ts
import { mkdirSync as mkdirSync4 } from "fs";
import { join as join4 } from "path";

// scripts/benchmark-campaign/full-f/shared/shared-admission.ts
init_paid_resource_proof_v2();
init_scientific_journal_proxy();
import { closeSync as closeSync3, fsyncSync as fsyncSync2, mkdirSync as mkdirSync3, openSync as openSync3, readFileSync as readFileSync2, writeFileSync as writeFileSync2 } from "fs";
import { join as join3, resolve as resolve4 } from "path";
function check(ok, code) {
  if (!ok)
    throw new Error(code);
}
var BENCH_CODES = { chembench: "11", chemiq: "12", skillsbench: "13", "terminal-bench": "14" };
function fullFConnection(root) {
  const c = JSON.parse(readFileSync2(join3(root, "docs/repair-2026-10-10/full-f-rerun/control.json"), "utf8"));
  check(c.paidReady === true && c.broker, "shared_broker_not_ready");
  return c.broker;
}
function fullFRunId(root, slug) {
  const c = fullFConnection(root);
  check(BENCH_CODES[slug], "bench_not_in_requested_scope");
  return c.runId + "-" + BENCH_CODES[slug] + "-" + new Date().toISOString().replace(/[:.]/g, "-");
}
async function rpc(connection, path, body, token) {
  const r = await fetch(connection.endpoint + path, { method: "POST", headers: { authorization: "Bearer " + connection.accessToken, "content-type": "application/json", ...token ? { "x-bench-lane-token": token } : {} }, body: JSON.stringify(body), signal: AbortSignal.timeout(30000) });
  const d = await r.json();
  check(r.ok, d.error ?? "broker_rpc_failed");
  return d;
}
async function acquireFullFAdmission(input) {
  const connection = input.connection ?? fullFConnection(input.root), claim = await rpc(connection, "/lane/claim", input), parent = jsonPin(claim.parentAdmissionPin);
  check(claim.protocol === "full-f-shared-lane-v1" && claim.runId === input.runId && parent.owned.ownerNonce === claim.owned.ownerNonce, "shared_lane_parent_binding");
  const laneProof = jsonPin(claim.proofPin);
  check(laneProof.runId === input.runId && laneProof.capUsd === claim.capUsd && same(laneProof.parentAdmissionPin, claim.parentAdmissionPin), "shared_lane_proof_binding");
  let closed = false;
  const assertOwned = () => {
    check(!closed, "shared_lane_closed");
    check(same(JSON.parse(readFileSync2(claim.canonicalLockPath, "utf8")), parent.owned), "shared_canonical_owner_changed");
  };
  const validateForwardSource = () => {
    assertOwned();
    verifyPin(claim.proofPin);
    verifyPin(claim.parentAdmissionPin);
    for (const pin of [...connection.sourcePins, ...input.sourcePins, claim.prices, claim.balance])
      verifyPin(pin);
    const status = JSON.parse(readFileSync2(claim.healthPath, "utf8"));
    check(status.pid === connection.pid && status.runId === connection.runId && status.healthy === true && Date.now() - Date.parse(status.atUtc) < 30000, "shared_broker_unhealthy");
    const prices = jsonPin(claim.prices);
    check(Date.now() >= Date.parse(prices.observedAtUtc) && Date.now() - Date.parse(prices.observedAtUtc) <= 86400000, "openrouter_price_expired");
  };
  const close = async (result) => {
    assertOwned();
    const receipt = await rpc(connection, "/lane/close?runId=" + encodeURIComponent(input.runId), { cashPin: result.cashPin }, claim.laneToken);
    closed = true;
    return receipt;
  };
  return {
    currency: "USD",
    root: input.root,
    path: claim.canonicalLockPath,
    runId: input.runId,
    capUsd: claim.capUsd,
    owned: claim.owned,
    proofPin: claim.proofPin,
    scope: "production",
    prices: claim.prices,
    balance: claim.balance,
    sourcePins: input.sourcePins,
    connection,
    assertOwned,
    validateForwardSource,
    registerCash(pin) {
      assertOwned();
      verifyPin(pin);
      mkdirSync3(resolve4(claim.registrationPath, ".."), { recursive: true });
      const fd = openSync3(claim.registrationPath, "wx", 384);
      try {
        writeFileSync2(fd, JSON.stringify({ runId: input.runId, cashPin: pin }) + `
`);
        fsyncSync2(fd);
      } finally {
        closeSync3(fd);
      }
    },
    async registerOwnedProcess(pin) {
      assertOwned();
      await rpc(connection, "/lane/process?runId=" + encodeURIComponent(input.runId), { pin }, claim.laneToken);
    },
    finishLightweight: close,
    async release(result) {
      await close(result);
    },
    async transport(raw) {
      try {
        validateForwardSource();
      } catch (error) {
        throw new ConfirmedNoForwardTransportFailure(String(error));
      }
      const headers = { authorization: "Bearer " + connection.accessToken, "x-bench-lane-token": claim.laneToken, "content-type": "application/json" };
      const deadline = Date.now() + 1200000;
      let response = await fetch(connection.endpoint + "/forward?runId=" + encodeURIComponent(input.runId), { method: "POST", headers, body: raw, signal: AbortSignal.timeout(30000) });
      let ticket;
      while (response.status === 202) {
        const pending = await response.json();
        check(pending.protocol === "full-f-forward-ticket-v1" && pending.runId === input.runId && typeof pending.ticket === "string" && (!ticket || ticket === pending.ticket), "invalid_forward_ticket");
        ticket = pending.ticket;
        check(Date.now() < deadline, "shared_forward_result_deadline");
        await Bun.sleep(250);
        response = await fetch(connection.endpoint + "/forward/result?runId=" + encodeURIComponent(input.runId) + "&ticket=" + encodeURIComponent(ticket), { headers, signal: AbortSignal.timeout(Math.min(30000, deadline - Date.now())) });
      }
      if (response.headers.get("x-bench-provider-attempted") === "false" && (!ticket || response.headers.get("x-bench-forward-ticket") === ticket)) {
        const rejection = await response.json();
        check(rejection?.error?.code === "bench_local_not_forwarded", "unproven_local_rejection");
        throw new ConfirmedNoForwardTransportFailure(rejection.error.message);
      }
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (response.headers.get("x-bench-body-complete") === "false")
        throw new CapturedTransportFailure({ httpStatus: response.status, rawBytes: bytes, bodyComplete: false, fault: response.headers.get("x-bench-fault") ?? "ProviderResponseBodyError" });
      return { httpStatus: response.status, rawResponse: new TextDecoder("utf8", { fatal: true }).decode(bytes) };
    }
  };
}

// scripts/benchmark-campaign/full-f/terminal-bench/isolated-run-directory.ts
async function reserveIsolatedRunDirectory(root, runsRoot) {
  while (true) {
    const runId = fullFRunId(root, "terminal-bench"), output = join4(runsRoot, runId);
    try {
      mkdirSync4(output);
      return { runId, output };
    } catch (error) {
      if (error.code !== "EEXIST")
        throw error;
      await Bun.sleep(2);
    }
  }
}

// scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts
var BENCHMARK_PROVIDER2 = Object.freeze({
  kind: "openrouter-deepseek",
  model: "deepseek/deepseek-v4.1-flash",
  canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
  baseURL: "https://openrouter.ai/api/v1",
  endpoint: "https://openrouter.ai/api/v1/chat/completions",
  keyEnv: "OPENROUTER_API_KEY",
  currency: "USD",
  providerName: "DigitalOcean",
  providerSlug: "digitalocean",
  peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
  routing: Object.freeze({ only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
  forcedToolMode: "constrained-auto"
});
function officialOpenRouterFault2(data, expectedProvider = BENCHMARK_PROVIDER2.providerName) {
  if (data?.provider !== expectedProvider)
    return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER2.model, BENCHMARK_PROVIDER2.canonicalModel].includes(data?.model))
    return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id)
    return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0)
    return "MissingOrInvalidOpenRouterUsdCost";
}
function openRouterRateLimitRejection2(data, status, providerName) {
  return status === 429 && data?.error?.code === 429 && data.error.metadata?.limit_source === "upstream_provider_shared_pool" && data.error.metadata.provider_name === providerName && typeof data.error.metadata.raw === "string" && data.error.metadata.raw.includes("temporarily rate-limited upstream") && !data.id && !data.usage && !data.choices;
}

// scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts
var BENCHMARK_INFERENCE2 = Object.freeze({
  maxTokens: 16384,
  reasoningEffort: "high",
  temperature: 0,
  seed: 42,
  retryTimes: 3,
  continueTimes: 3
});
function benchmarkProviderRequest2(body, profile = BENCHMARK_INFERENCE2, provider) {
  const choice = body.tool_choice;
  const forced = choice === "required" || choice?.type === "function" && typeof choice.function?.name === "string";
  const effort = provider ? profile.reasoningEffort : forced ? "none" : profile.reasoningEffort;
  const thinking = forced ? "disabled" : "enabled";
  const limits = [body.max_tokens, body.max_completion_tokens].filter((value) => value !== undefined && value !== null);
  if (body.temperature !== profile.temperature || body.seed !== profile.seed && !(provider && body.seed === undefined) || body.reasoning_effort !== effort || !limits.length || limits.some((value) => value !== profile.maxTokens) || body.thinking !== undefined && body.thinking?.type !== (provider ? "enabled" : thinking)) {
    throw new Error("Wire parameters differ from the benchmark inference profile");
  }
  const wire = { ...body, thinking: { type: thinking }, max_tokens: profile.maxTokens };
  delete wire.max_completion_tokens;
  if (provider) {
    if (body.model !== provider.model || profile.reasoningEffort !== "high")
      throw Error("OpenRouter V4.1 Flash high-thinking profile required");
    if (forced) {
      const name = choice?.function?.name;
      if (typeof name !== "string")
        throw Error("Constrained auto submission requires a named tool");
      wire.tools = (body.tools ?? []).filter((tool) => tool.type === "function" && tool.function?.name === name);
      if (wire.tools.length !== 1)
        throw Error("The required submit tool is absent or duplicated");
      wire.tool_choice = "auto";
    }
    wire.provider = { ...BENCHMARK_PROVIDER2.routing };
    wire.reasoning = { enabled: true, effort: "high", exclude: false };
    delete wire.thinking;
    delete wire.reasoning_effort;
    delete wire.seed;
  }
  return wire;
}

// scripts/benchmark-campaign/full-f/shared/digitalocean-closed-run-cost.ts
import { readFileSync as readFileSync9 } from "fs";
import { join as join11 } from "path";

// scripts/benchmark-campaign/full-f/shared/digitalocean-usd-cash.ts
import { closeSync as closeSync7, fsyncSync as fsyncSync6, openSync as openSync7, readFileSync as readFileSync6, readSync as readSync5, statSync as statSync6, writeSync as writeSync4 } from "fs";
import { join as join8, resolve as resolve8 } from "path";

// scripts/benchmark-campaign/full-f/shared/digitalocean-journal.ts
init_campaign_contract();
import { createHash as createHash3, randomBytes } from "crypto";
import { closeSync as closeSync4, existsSync as existsSync2, fstatSync, fsyncSync as fsyncSync3, lstatSync as lstatSync2, mkdirSync as mkdirSync5, openSync as openSync4, readFileSync as readFileSync3, readSync as readSync2, readdirSync, realpathSync as realpathSync2, renameSync, statSync as statSync3, writeSync } from "fs";
import { isAbsolute as isAbsolute2, join as join5, relative as relative2, resolve as resolve5 } from "path";
import { gunzipSync as gunzipSync2, gzipSync as gzipSync2 } from "zlib";
var CAMPAIGN_JOURNAL_PROTOCOL = "campaign-api-journal-v1";
var OPENROUTER_JOURNAL_PROTOCOL = "campaign-api-journal-openrouter-v1";
var MAX_LINE = 64 * 1024;
var MAX_REQUEST = 4 * 1024 * 1024;
var MAX_RESPONSE = 64 * 1024 * 1024;
var MAX_JOURNAL = 2 * 1024 * 1024 * 1024;
var EPS = 0.000000001;
var WIRE = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
var hash2 = (data) => createHash3("sha256").update(data).digest("hex");
var json = (value) => JSON.stringify(value);
var same2 = (a, b) => json(a) === json(b);
var finite = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;

class CampaignJournalError extends Error {
  code;
  stage;
  constructor(code, stage) {
    super(code + (stage ? ":" + stage : ""));
    this.name = "CampaignJournalError";
    this.code = code;
    this.stage = stage;
  }
}
function demand2(ok, code) {
  if (!ok)
    throw new CampaignJournalError(code);
}
function ordinaryDirectory2(path) {
  demand2(isAbsolute2(path), "absolute_directory_required");
  mkdirSync5(path, { recursive: true });
  demand2(lstatSync2(path).isDirectory() && !lstatSync2(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync2(path);
}
function regularInStore(path, store) {
  const full = resolve5(path), rel = relative2(store, full);
  demand2(rel && !rel.startsWith("..") && !isAbsolute2(rel), "raw_outside_store");
  let current = store;
  for (const component of rel.split(/[\\/]/)) {
    current = join5(current, component);
    const s = lstatSync2(current);
    demand2(!s.isSymbolicLink(), "raw_reparse");
  }
  demand2(lstatSync2(full).isFile() && realpathSync2(full) === full, "raw_not_regular");
  return full;
}
function fileHash2(path) {
  const before = statSync3(path), fd = openSync4(path, "r"), digest2 = createHash3("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync2(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand2(n > 0, "hash_short_read");
      digest2.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync4(fd);
  }
  const after = statSync3(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest2.digest("hex");
}
function rawEvidence(path, expected, compressedExpected, store, parse = true) {
  regularInStore(path, store);
  const before = statSync3(path);
  const zipped = readFileSync3(path);
  demand2(zipped.length <= MAX_RESPONSE + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync2(zipped, { maxOutputLength: MAX_RESPONSE });
  const after = statSync3(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(zipped) === compressedExpected && hash2(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand2(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand2(["deepseek", "relace", "digitalocean"].includes(slug) && (config.providerName === undefined || config.providerName === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[slug]), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand2(config.providerRouting === undefined || same2(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues2(raw, data, config) {
  demand2(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand2(same2(data.provider, frozenRouting(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
  const limit = checkedOutputTokens(data);
  demand2(Array.isArray(data.messages), "invalid_request_messages");
  const reservationUsd = ((raw.length + 2048 + data.messages.length * 256) * 0.3 + limit * 1.2) / 1e6;
  return { reservationUsd, wireParameters: Object.fromEntries(WIRE.filter((k) => (k in data)).map((k) => [k, data[k]])) };
}
function checkedStart(c, seq, store, config) {
  demand2(typeof c.route === "string" && c.route.length > 0 && Buffer.byteLength(c.route) <= 1024 && !/[\r\n\0]/.test(c.route), "invalid_route");
  demand2(Number.isFinite(Date.parse(c.startedAt)) && c.providerAttempted === false, "invalid_start_receipt");
  demand2(c.requestFile === join5(store, `provider-${seq}-request.json.gz`), "request_sequence_path");
  const { raw, data } = rawEvidence(c.requestFile, c.requestSha256, c.requestCompressedSha256, store);
  const expected = requestValues2(raw, data, config);
  demand2(raw.length === c.requestBytes && c.requestedModel === data.model && same2(c.wireParameters, expected.wireParameters) && finite(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS, "request_receipt_mismatch");
}
function routingRejection(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection2(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand2(same2(c[key], start[key]), "finish_start_mismatch");
  demand2(typeof c.providerAttempted === "boolean" && typeof c.finishedAt === "string" && Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
  if (!c.providerAttempted)
    demand2(c.confirmedNoForward === true && !c.responseFile && !c.usage, "unproven_zero_charge");
  let rejectedBeforeGeneration = false, rateLimited = false;
  if (c.responseFile) {
    demand2(c.providerAttempted && c.responseFile === join5(store, `provider-${seq}-response.json.gz`) && c.responseSha256 && c.responseCompressedSha256, "response_sequence_path");
    const { raw } = rawEvidence(c.responseFile, c.responseSha256, c.responseCompressedSha256, store, false);
    let data;
    try {
      data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {}
    if (data && typeof data === "object") {
      rejectedBeforeGeneration = routingRejection(config, data, c.httpStatus);
      rateLimited = rateRejection(config, data, c.httpStatus);
      demand2(same2(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
      if (config.provider) {
        demand2((typeof data.provider === "string" ? data.provider : undefined) === c.providerName, "provider_receipt_mismatch");
        const routeFault = c.httpStatus === 200 ? officialOpenRouterFault2(data, config.providerName ?? "DeepSeek") : undefined;
        if (routeFault)
          demand2(c.fault === routeFault, "official_provider_fault_missing");
      }
      if (c.httpStatus === 200)
        demand2(c.completionValid === !completionFault(data) && c.completionFault === completionFault(data), "completion_receipt_mismatch");
    } else
      demand2(c.fault && c.usage === undefined && c.servedModel === undefined && c.requestId === undefined && c.completionValid === undefined, "invalid_json_receipt_mismatch");
  } else
    demand2(c.fault && !c.usage && c.servedModel === undefined && c.requestId === undefined, "missing_response_evidence");
  demand2(c.nonGenerationRejection === (rateLimited ? "upstream_rate_limit" : undefined), "rate_rejection_raw_binding");
  const expected = { usage: c.usage };
  reconcileReceiptCost(expected, start.reservationUsd, { provider: config.provider, knownUncharged: rateLimited || rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
  demand2(c.billedCostUsd === expected.billedCostUsd, "reported_usd_cost_mismatch");
  demand2(c.reservationUsd === start.reservationUsd && c.costBasis === expected.costBasis && finite(c.usdUpperBound) && finite(c.accountedUpperBoundUsd) && Math.abs(c.usdUpperBound - expected.usdUpperBound) <= EPS && c.usdUpperBound === c.accountedUpperBoundUsd, "cost_receipt_mismatch");
}
function pendingOf(active) {
  const result = new Map;
  for (const c of active.values())
    result.set(c.route, (result.get(c.route) ?? 0) + 1);
  return Object.fromEntries(result);
}
function reserveOf(active) {
  let n = 0;
  for (const c of active.values())
    n += c.reservationUsd;
  return n;
}
function financialState(config, configSha256, active, accepted, finished, spent, prefix, stopReason) {
  return { protocol: config.protocol, ...config.provider ? { currency: "USD", provider: config.provider } : {}, campaign: config.campaign, configSha256, capUsd: config.capUsd, priorCampaignCostUpperBoundUsd: config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserveOf(active), pending: pendingOf(active), active: [...active].map(([requestSeq, c]) => ({ requestSeq, route: c.route, requestSha256: c.requestSha256, reservationUsd: c.reservationUsd })), acceptedRequestCount: accepted, finishedRequestCount: finished, durablePrefix: { ...prefix }, ...stopReason ? { stopReason } : {} };
}
function* lines(fd, length) {
  let offset = 0, at = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at < length) {
    const n = readSync2(fd, buffer, 0, Math.min(buffer.length, length - at), at);
    demand2(n > 0, "journal_short_read");
    at += n;
    carry = Buffer.concat([carry, buffer.subarray(0, n)]);
    for (;; ) {
      const newline = carry.indexOf(10);
      if (newline < 0)
        break;
      const line = carry.subarray(0, newline + 1);
      demand2(line.length <= MAX_LINE, "journal_line_limit");
      yield { offset, line };
      offset += line.length;
      carry = carry.subarray(newline + 1);
    }
    demand2(carry.length <= MAX_LINE, "journal_line_limit");
  }
  demand2(carry.length === 0, "truncated_journal");
}
function inspectCampaignJournal(directory) {
  return inspect(directory);
}
function inspect(directory, ownedExport) {
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join5(resolve5(directory), "api-events.jsonl"), directory: resolve5(directory) };
  let fd;
  try {
    const store = realpathSync2(directory);
    demand2(store === resolve5(directory), "journal_directory_identity");
    const configBytes = readFileSync3(join5(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL && config.model === BENCHMARK_PROVIDER2.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting(config);
    demand2(providerValid && Number.isSafeInteger(config.pendingLimit) && config.pendingLimit >= 4 && config.pendingLimit <= 50 && config.maxLineBytes === MAX_LINE && config.maxJournalBytes === MAX_JOURNAL && finite(config.capUsd) && config.capUsd > 0 && finite(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash2(configBytes), before = statSync3(result.journalPath);
    demand2(before.size <= MAX_JOURNAL && lstatSync2(result.journalPath).isFile() && !lstatSync2(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync4(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand2(same2(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json(e) + `
`).equals(line), "unknown_or_noncanonical_event");
      demand2(e.protocol === config.protocol && e.eventSeq === prefix.eventCount && e.previousEventSha256 === prefix.lastSha256 && Number.isSafeInteger(e.requestSeq) && e.requestSeq >= 0, "journal_chain_or_sequence");
      if (e.kind === "start") {
        demand2(e.requestSeq === accepted && active.size < config.pendingLimit && !active.has(e.requestSeq), "duplicate_or_unbounded_start");
        checkedStart(e.record, e.requestSeq, store, config);
        demand2(config.priorCampaignCostUpperBoundUsd + spent + reserveOf(active) + e.record.reservationUsd <= config.capUsd + EPS, "admission_exceeded_cap");
        active.set(e.requestSeq, e.record);
        accepted++;
      } else if (e.kind === "finish") {
        const start = active.get(e.requestSeq);
        demand2(start && !result.offsets.has(e.requestSeq), "duplicate_or_unknown_finish");
        checkedFinish(e.record, start, e.requestSeq, store, config);
        if (e.record.requestId) {
          demand2(!ids.has(e.record.requestId), "duplicate_provider_id");
          ids.add(e.record.requestId);
        }
        spent += e.record.usdUpperBound;
        active.delete(e.requestSeq);
        finished++;
        allProviderValid &&= isNonGenerationRateRejection(e.record) || e.record.providerAttempted && e.record.httpStatus === 200 && e.record.completionValid === true && validTokenUsage(e.record.usage) && !e.record.fault;
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash2(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash2(line) };
      result.snapshot = financialState(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync3(join5(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand2(same2(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand2(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand2(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand2(ownedExport.path === join5(store, "api-ledger.json.partial") && statSync3(ownedExport.path).size === ownedExport.bytes && fileHash2(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand2(!existsSync2(join5(store, "journal-error.json")) && !readdirSync(store).some((n) => n.includes(".partial") && join5(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync3(result.journalPath);
    demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(readFileSync3(join5(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync4(fd);
  }
  return result;
}
function createCampaignJournal(options, hooks = {}) {
  return new CampaignJournal(options, hooks);
}

class CampaignJournal {
  hooks;
  directory;
  outputDirectory;
  config;
  configSha256;
  journalPath;
  fd = -1;
  prefix;
  journalMtime = 0;
  lastLine;
  active = new Map;
  accepted = 0;
  finished = 0;
  spent = 0;
  stopReason;
  poisoned;
  exported = false;
  closedProof;
  closed = false;
  providerIds = new Set;
  metrics = { journalBytesWritten: 0, checkpointBytesWritten: 0, rawGzipBytesWritten: 0, exportBytesWritten: 0, fsyncCallsReturned: 0, maxHotMetadataBytes: 0 };
  constructor(options, hooks) {
    this.hooks = hooks;
    demand2(finite(options.capUsd) && options.capUsd > 0 && finite(options.priorCampaignCostUpperBoundUsd) && /^repair-[0-9TZ-]+$/.test(options.campaign), "invalid_journal_options");
    this.directory = ordinaryDirectory2(resolve5(options.directory));
    this.outputDirectory = ordinaryDirectory2(resolve5(options.outputDirectory ?? options.directory));
    demand2(!readdirSync(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
    if (options.provider)
      demand2(options.provider.kind === BENCHMARK_PROVIDER2.kind && options.provider.model === BENCHMARK_PROVIDER2.model, "unsupported_journal_provider");
    this.config = { protocol: options.provider ? OPENROUTER_JOURNAL_PROTOCOL : CAMPAIGN_JOURNAL_PROTOCOL, campaign: options.campaign, capUsd: options.capUsd, priorCampaignCostUpperBoundUsd: options.priorCampaignCostUpperBoundUsd, pendingLimit: 50, model: options.provider?.model ?? "deepseek-flash", ...options.provider ? {
      provider: options.provider.kind,
      currency: "USD",
      providerName: options.provider.providerName,
      providerSlug: options.provider.providerSlug,
      providerRouting: options.provider.routing,
      zeroChargePolicy: "explicit-rate-rejection-v2"
    } : {}, maxLineBytes: MAX_LINE, maxJournalBytes: MAX_JOURNAL, createdAt: new Date().toISOString() };
    const configRaw = Buffer.from(JSON.stringify(this.config, null, 2) + `
`);
    this.configSha256 = hash2(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join5(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join5(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync4(this.journalPath, "wx+");
      this.sync(this.fd, this.journalPath, "journal:create");
      this.journalMtime = fstatSync(this.fd).mtimeMs;
      this.checkpoint("create");
    } catch (e) {
      this.close();
      if (e instanceof CampaignJournalError)
        throw e;
      throw new CampaignJournalError("journal_create_io", e.code);
    }
  }
  write(fd, path, raw, stage, metric) {
    let at = 0;
    while (at < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at };
      this.hooks.before?.(op);
      const n = writeSync(fd, raw, at, raw.length - at);
      demand2(n > 0, "short_write");
      this.metrics[metric] += n;
      at += n;
      this.hooks.after?.({ ...op, bytes: n });
    }
  }
  sync(fd, path, stage) {
    const op = { kind: "fsync", stage, path, fd };
    this.hooks.before?.(op);
    fsyncSync3(fd);
    this.metrics.fsyncCallsReturned++;
    this.hooks.after?.(op);
  }
  persistExclusive(path, raw, stage, metric) {
    const fd = openSync4(path, "wx", 384);
    try {
      this.write(fd, path, raw, stage, metric);
      this.sync(fd, path, stage);
    } finally {
      try {
        closeSync4(fd);
      } catch {}
    }
  }
  state() {
    return financialState(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason);
  }
  snapshot() {
    return { ...this.state(), ...this.poisoned ? { error: this.poisoned.code } : {}, metrics: { ...this.metrics } };
  }
  poison(code, stage, uncommittedReceipt) {
    const error = this.poisoned ?? new CampaignJournalError(code, stage);
    this.poisoned = error;
    try {
      this.persistExclusive(join5(this.directory, "journal-error.json"), Buffer.from(json({ protocol: CAMPAIGN_JOURNAL_PROTOCOL, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
`), "error_diagnostic", "checkpointBytesWritten");
    } catch {}
    throw error;
  }
  writable() {
    if (this.poisoned)
      throw new CampaignJournalError("journal_poisoned", this.poisoned.code);
    demand2(!this.closed, "writer_closed");
    demand2(!this.exported, "already_exported");
    try {
      const checkpointPath = join5(this.directory, "api-state.json");
      regularInStore(checkpointPath, this.directory);
      const checkpoint = readFileSync3(checkpointPath);
      if (checkpoint.length > MAX_LINE || !checkpoint.equals(Buffer.from(json(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync2(join5(this.directory, "journal-error.json")))
      this.poison("journal_changed", "unexpected_error_marker");
    try {
      regularInStore(join5(this.directory, "journal-config.json"), this.directory);
      if (fileHash2(join5(this.directory, "journal-config.json")) !== this.configSha256)
        this.poison("journal_changed", "config_changed");
    } catch {
      this.poison("journal_changed", "config_changed");
    }
    try {
      const s = fstatSync(this.fd), disk = lstatSync2(this.journalPath);
      if (!disk.isFile() || disk.isSymbolicLink() || disk.ino !== s.ino || disk.dev !== s.dev || s.size !== this.prefix.bytes || s.mtimeMs !== this.journalMtime)
        this.poison("journal_changed", "before_append");
      if (this.lastLine) {
        const raw = Buffer.alloc(this.lastLine.bytes);
        const n = readSync2(this.fd, raw, 0, raw.length, this.lastLine.offset);
        if (n !== raw.length || hash2(raw) !== this.lastLine.sha256)
          this.poison("journal_changed", "last_durable_line");
      }
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison("journal_identity_io", "before_append");
    }
  }
  checkpoint(stage) {
    const target = join5(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes(8).toString("hex");
    const raw = Buffer.from(json(this.state()) + `
`);
    demand2(raw.length <= MAX_LINE, "checkpoint_resource_limit");
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    try {
      this.persistExclusive(temp, raw, "checkpoint:" + stage, "checkpointBytesWritten");
      const op = { kind: "rename", stage: "checkpoint:" + stage, path: target };
      this.hooks.before?.(op);
      renameSync(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("checkpoint_io", stage);
    }
  }
  append(kind, seq, receipt, apply) {
    const e = { protocol: this.config.protocol, eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, requestSeq: seq, record: receipt };
    const raw = Buffer.from(json(e) + `
`);
    if (raw.length > MAX_LINE || this.prefix.bytes + raw.length > MAX_JOURNAL)
      this.poison("journal_resource_limit", `${kind}:${seq}`, receipt);
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => {
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash2(raw) };
      this.lastLine = { offset, bytes: raw.length, sha256: this.prefix.lastSha256 };
      apply();
    };
    try {
      this.write(this.fd, this.journalPath, raw, `journal:${kind}:${seq}`, "journalBytesWritten");
      this.sync(this.fd, this.journalPath, `journal:${kind}:${seq}`);
    } catch {
      if (this.metrics.fsyncCallsReturned > fsyncBefore)
        commit();
      this.poison("journal_io", `${kind}:${seq}`, receipt);
    }
    commit();
    try {
      this.journalMtime = fstatSync(this.fd).mtimeMs;
    } catch {
      this.poison("journal_identity_io", `${kind}:${seq}`, receipt);
    }
    this.checkpoint(`${kind}:${seq}`);
  }
  admit(input) {
    this.writable();
    if (this.stopReason)
      return { admitted: false, reason: this.stopReason };
    if (this.active.size >= this.config.pendingLimit)
      return { admitted: false, reason: "pending_limit" };
    demand2(typeof input.rawRequest === "string" && Buffer.byteLength(input.rawRequest) <= MAX_REQUEST, "request_resource_limit");
    demand2(typeof input.route === "string" && input.route.length > 0 && Buffer.byteLength(input.route) <= 1024 && !/[\r\n\0]/.test(input.route), "invalid_route");
    const raw = Buffer.from(input.rawRequest), data = JSON.parse(input.rawRequest), values = requestValues2(raw, data, this.config);
    if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) + values.reservationUsd > this.config.capUsd) {
      this.stopReason = "local_budget_exhausted";
      this.checkpoint("budget_stop");
      return { admitted: false, reason: this.stopReason };
    }
    const seq = this.accepted, requestFile = join5(this.directory, `provider-${seq}-request.json.gz`), zipped = gzipSync2(raw);
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash2(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash2(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
    demand2(Number.isFinite(Date.parse(c.startedAt)), "invalid_start_time");
    this.active.set(seq, c);
    try {
      this.persistExclusive(requestFile, zipped, `raw_request:${seq}`, "rawGzipBytesWritten");
    } catch {
      this.poison("raw_capture_io", `start:${seq}`, c);
    }
    this.append("start", seq, c, () => {
      this.accepted++;
    });
    return { admitted: true, requestSeq: seq, reservationUsd: values.reservationUsd, requestFile, requestSha256: c.requestSha256 };
  }
  finish(input) {
    this.writable();
    try {
      return this.finishReceipt(input);
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison(e instanceof CampaignJournalError ? e.code : "finish_input_error", "finish_input");
    }
  }
  finishReceipt(input) {
    const start = this.active.get(input.requestSeq);
    if (!start)
      this.poison(input.requestSeq < this.accepted ? "duplicate_finish" : "unknown_finish", "finish");
    const c = { ...start, providerAttempted: input.providerAttempted };
    demand2(typeof input.providerAttempted === "boolean", "invalid_provider_attempt");
    if (!input.providerAttempted) {
      demand2(input.confirmedNoForward === true && input.rawResponse === undefined, "unproven_zero_charge");
      c.confirmedNoForward = true;
    }
    if (input.httpStatus !== undefined) {
      demand2(Number.isInteger(input.httpStatus) && input.httpStatus >= 100 && input.httpStatus <= 599, "invalid_http_status");
      c.httpStatus = input.httpStatus;
    }
    let rejectedBeforeGeneration = false;
    if (input.rawResponse !== undefined) {
      demand2(input.providerAttempted && typeof input.rawResponse === "string" && Buffer.byteLength(input.rawResponse) <= MAX_RESPONSE, "response_resource_limit");
      const raw = Buffer.from(input.rawResponse), zipped = gzipSync2(raw), responseFile = join5(this.directory, `provider-${input.requestSeq}-response.json.gz`);
      c.responseFile = responseFile;
      c.responseSha256 = hash2(raw);
      c.responseCompressedSha256 = hash2(zipped);
      try {
        this.persistExclusive(responseFile, zipped, `raw_response:${input.requestSeq}`, "rawGzipBytesWritten");
      } catch {
        this.poison("raw_capture_io", `finish:${input.requestSeq}`, c);
      }
      try {
        const data = JSON.parse(input.rawResponse);
        rejectedBeforeGeneration = routingRejection(this.config, data, input.httpStatus);
        if (rateRejection(this.config, data, input.httpStatus)) {
          c.nonGenerationRejection = "upstream_rate_limit";
          rejectedBeforeGeneration = true;
        }
        if (this.config.provider) {
          c.providerName = typeof data.provider === "string" ? data.provider : undefined;
          if (input.httpStatus === 200)
            c.fault = officialOpenRouterFault2(data, this.config.providerName ?? "DeepSeek");
        }
        c.servedModel = typeof data.model === "string" ? data.model : undefined;
        c.requestId = typeof data.id === "string" ? data.id : undefined;
        if (data.usage && typeof data.usage === "object")
          c.usage = data.usage;
        if (input.httpStatus === 200) {
          c.completionFault = completionFault(data);
          c.completionValid = !c.completionFault;
        }
      } catch {
        c.fault = "InvalidProviderJSON";
      }
    }
    if (input.fault) {
      demand2(typeof input.fault === "string" && Buffer.byteLength(input.fault) <= 2048, "fault_resource_limit");
      c.fault = input.fault;
    }
    if (!c.responseFile && !c.fault)
      c.fault = input.providerAttempted ? "UncapturedProviderTransport" : "LocalBeforeForwardError";
    reconcileReceiptCost(c, start.reservationUsd, { provider: this.config.provider, knownUncharged: rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
    c.finishedAt = input.finishedAt ?? new Date().toISOString();
    demand2(Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
    if (c.requestId && this.providerIds.has(c.requestId))
      this.poison("duplicate_provider_id", "finish", c);
    this.append("finish", input.requestSeq, c, () => {
      this.spent += c.usdUpperBound;
      this.active.delete(input.requestSeq);
      this.finished++;
      if (c.requestId)
        this.providerIds.add(c.requestId);
      if (c.usdUpperBound > start.reservationUsd + EPS)
        this.stopReason ??= "usage_exceeded_reservation";
      if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) > this.config.capUsd + EPS)
        this.stopReason ??= "actual_cost_exceeded_cap";
      if (!isNonGenerationRateRejection(c) && (c.fault || c.httpStatus !== 200 || c.completionValid !== true || !validTokenUsage(c.usage)))
        this.stopReason ??= "provider_fault";
    });
    return { requestSeq: input.requestSeq, receipt: { ...c }, accountingCommitted: true };
  }
  readReceipt(fd, offset) {
    const line = Buffer.alloc(offset.bytes);
    demand2(readSync2(fd, line, 0, line.length, offset.offset) === line.length && hash2(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand2(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand2(statSync3(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync4(this.journalPath, "r");
    const indices = route === undefined ? Array.from({ length: this.accepted }, (_, i) => i) : [...proof.routes.get(route) ?? []].sort((a, b) => a - b);
    try {
      for (const seq of indices) {
        const offset = proof.offsets.get(seq);
        demand2(offset, "missing_finish_offset");
        const c = this.readReceipt(fd, offset);
        const start = { ...c, providerAttempted: false };
        checkedStart(start, seq, this.directory, this.config);
        checkedFinish(c, start, seq, this.directory, this.config);
        yield c;
      }
    } finally {
      closeSync4(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand2(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same2(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS)
      this.poison("export_integrity", "before_export");
    const target = join5(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand2(!existsSync2(target) && !existsSync2(temp), "existing_export");
    const fd = openSync4(temp, "wx", 384), journalFd = openSync4(this.journalPath, "r");
    try {
      const header = { ...this.config.provider ? { protocol: this.config.protocol, currency: "USD", provider: this.config.provider, model: this.config.model } : {}, campaign: this.config.campaign, capUsd: this.config.capUsd, priorCampaignCostUpperBoundUsd: this.config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: this.spent, reservedUpperBoundUsd: 0, ...this.stopReason ? { fatal: this.stopReason } : {}, pending: {}, captureErrors: [], calls: [] };
      const opening = JSON.stringify(header, null, 2).replace(/\[\]\n}$/, `[
`);
      this.write(fd, temp, Buffer.from(opening), "legacy_export", "exportBytesWritten");
      for (let seq = 0;seq < this.accepted; seq++) {
        const offset = proof.offsets.get(seq);
        demand2(offset, "missing_finish_offset");
        const text = JSON.stringify(this.readReceipt(journalFd, offset), null, 2).split(`
`).map((line) => "    " + line).join(`
`);
        this.write(fd, temp, Buffer.from(text + (seq + 1 < this.accepted ? `,
` : `
`)), "legacy_export", "exportBytesWritten");
      }
      this.write(fd, temp, Buffer.from(`  ]
}
`), "legacy_export", "exportBytesWritten");
      this.sync(fd, temp, "legacy_export");
    } catch {
      this.poison("export_io", "legacy_export");
    } finally {
      try {
        closeSync4(fd);
      } catch {}
      closeSync4(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync3(temp).size, sha256: fileHash2(temp) } : undefined;
    const after = inspect(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same2(after.prefix, proof.prefix))
      this.poison("export_integrity", "after_export");
    try {
      const op = { kind: "rename", stage: "legacy_export", path: target };
      this.hooks.before?.(op);
      renameSync(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("export_io", "legacy_rename");
    }
    this.exported = true;
    this.closedProof = after;
    return { path: target, bytes: statSync3(target).size, sha256: fileHash2(target), accountingClosed: true, eligibleForScoreCertification: proof.eligibleForScoreCertification, durablePrefix: { ...this.prefix }, legacyCompletedNotSet: true };
  }
  close() {
    if (!this.closed) {
      try {
        closeSync4(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}

// scripts/benchmark-campaign/full-f/shared/digitalocean-usd-cash.ts
init_cny_cash_shadow_v2();
init_paid_resource_proof_v2();
function durable(path, value) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`), fd = openSync7(path, "wx", 384);
  try {
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync4(fd, raw, at, raw.length - at);
      demand(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync6(fd);
  } finally {
    closeSync7(fd);
  }
  demand(readFileSync6(path).equals(raw), "usd_cash_readback");
  return actualPin(path);
}
function validateUsdPrices(pin, providerSlug = BENCHMARK_PROVIDER2.providerSlug) {
  const data = jsonPin(pin);
  demand(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER2.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand(same(data.reservationRates, BENCHMARK_PROVIDER2.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand(raw.data?.endpoints?.some((row) => row.provider_name === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[providerSlug] && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER2.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart(directory, data) {
  const raw = readFileSync6(join8(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand(hash(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route && same(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}
class UsdCash {
  options;
  states = new Map;
  tickets = new WeakSet;
  events = [];
  poisonReason;
  closed;
  fd;
  previousHash;
  capUsd;
  bytes = 0;
  directory;
  configPin;
  prices;
  config;
  constructor(options) {
    this.options = options;
    const admission = options.admission;
    demand(options.providerKind === "local-mock" || admission?.currency === "USD", "openrouter_usd_admission_required");
    this.directory = ordinaryDirectory(options.directory);
    this.prices = validateUsdPrices(options.prices);
    const config = jsonPin(options.journal.configPin);
    demand(config.provider === "openrouter-deepseek" && config.currency === "USD" && config.campaign === options.runId && config.priorCampaignCostUpperBoundUsd === 0, "openrouter_cash_journal_binding");
    this.capUsd = admission?.capUsd ?? config.capUsd;
    demand(Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd, "openrouter_cash_cap_binding");
    this.config = {
      protocol: "openrouter-usd-cash-config-v1",
      runId: options.runId,
      currency: "USD",
      providerKind: options.providerKind,
      capUsd: this.capUsd,
      ownerNonce: admission?.owned.ownerNonce ?? null,
      scope: admission?.scope ?? "local-mock",
      admissionPin: admission?.proofPin ?? null,
      pricesPin: options.prices,
      journal: options.journal,
      sourcePin: actualPin(import.meta.path),
      createdAt: new Date().toISOString(),
      invoice: false,
      foreignExchangeConversion: false
    };
    this.configPin = durable(join8(this.directory, "cash-config.json"), this.config);
    this.previousHash = this.configPin.sha256;
    this.fd = openSync7(join8(this.directory, "cash-events.jsonl"), "wx+", 384);
    fsyncSync6(this.fd);
    try {
      admission?.registerCash(this.configPin);
    } catch (error) {
      closeSync7(this.fd);
      throw error;
    }
  }
  append(kind, data) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + `
`);
    demand(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync4(this.fd, raw, at, raw.length - at, this.bytes + at);
      demand(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync6(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand(readSync5(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw) && statSync6(join8(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash(raw);
    this.events.push(event);
  }
  snapshot() {
    let known = 0, pending = 0, unknown = 0, pendingCount = 0, unknownCount = 0;
    for (const state of this.states.values()) {
      if (state.phase === "known")
        known += state.amount;
      if (state.phase === "pending") {
        pending += state.ticket.reservationUsd;
        pendingCount++;
      }
      if (state.phase === "unknown") {
        unknown += state.amount;
        unknownCount++;
      }
    }
    return {
      protocol: "openrouter-usd-cash-state-v1",
      currency: "USD",
      runId: this.options.runId,
      capUsd: this.capUsd,
      billedUsd: known,
      pendingReservationUsd: pending,
      unknownReservationUsd: unknown,
      exposureUpperBoundUsd: known + pending + unknown,
      remainingUsd: this.capUsd - known - pending - unknown,
      pendingCount,
      newUnknownCount: unknownCount,
      poisoned: !!this.poisonReason,
      poisonReason: this.poisonReason ?? null,
      invoice: false,
      foreignExchangeConversion: false
    };
  }
  poison(reason) {
    this.poisonReason ??= reason;
  }
  beforeForward(input) {
    demand(!this.closed && !this.poisonReason, "usd_cash_closed_or_poisoned");
    const admission = this.options.admission;
    admission?.validateForwardSource();
    verifyPin(this.options.prices);
    verifyPin(this.config.sourcePin);
    verifyPin(this.options.journal.sourcePin);
    const observed = Date.parse(this.prices.observedAtUtc);
    if (this.options.providerKind === "real-provider")
      demand(Number.isFinite(observed) && Date.now() >= observed && Date.now() - observed <= 86400000, "openrouter_price_expired");
    const j = input.journal.admitted, raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2);
    const inspected = inspectCampaignJournal(this.options.journal.directory);
    demand(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve8(input.capturedRequest.path) === resolve8(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
    const reservationUsd = this.options.providerKind === "local-mock" ? 0 : j.reservationUsd;
    const permitted = this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 0.000000001;
    const ticket = Object.freeze({
      requestSeq: j.requestSeq,
      route: input.route,
      reservationUsd,
      currency: "USD",
      dispatchAllowed: permitted
    });
    const start = { ticket, requestPin: input.capturedRequest, requestSha256: j.requestSha256, startPrefix: input.journal.startPrefix };
    demand(boundStart(this.options.journal.directory, start).reservationUsd === j.reservationUsd, "usd_actual_reservation_binding");
    this.append("start", start);
    this.states.set(j.requestSeq, { ticket, phase: permitted ? "pending" : "denied", amount: 0 });
    this.tickets.add(ticket);
    if (!permitted)
      this.poison("usd_envelope_exhausted");
    return { admitted: permitted, ticket, ...!permitted ? { reason: "usd_envelope_exhausted" } : {} };
  }
  finish(given, finish) {
    demand(!this.closed && this.tickets.has(given), "usd_ticket_not_owned");
    const ticket = given, state = this.states.get(ticket.requestSeq);
    const signature = hash(JSON.stringify(finish));
    if (state.signature) {
      demand(state.signature === signature, "usd_duplicate_finish_changed");
      return this.snapshot();
    }
    let phase, amount, receipt;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync6(join8(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand(hash(line) === ref.finishLineSha256, "usd_finish_line_changed");
      const event = JSON.parse(line.toString("utf8"));
      receipt = event.record;
      demand(event.kind === "finish" && event.requestSeq === ticket.requestSeq && receipt.route === ticket.route && inspectCampaignJournal(this.options.journal.directory).valid, "usd_finish_journal_binding");
      phase = receipt.costBasis === "reservation" ? "unknown" : "known";
      amount = this.options.providerKind === "local-mock" ? 0 : receipt.usdUpperBound;
    } else {
      phase = "unknown";
      amount = ticket.reservationUsd;
      this.poison("usd_failed_capture_unsettled");
    }
    demand(Number.isFinite(amount) && amount >= 0, "usd_finish_amount_invalid");
    this.append("finish", {
      ticket,
      signature,
      phase,
      amountUsd: amount,
      finish,
      costBasis: receipt?.costBasis ?? "reservation",
      generationId: receipt?.requestId ?? null,
      providerName: receipt?.providerName ?? null,
      servedModel: receipt?.servedModel ?? null
    });
    state.phase = phase;
    state.amount = amount;
    state.signature = signature;
    if (phase === "unknown")
      this.poison("usd_unknown_charge");
    if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 0.000000001)
      this.poison("usd_cost_exceeded_cap");
    return this.snapshot();
  }
  close() {
    if (this.closed)
      return this.closed;
    fsyncSync6(this.fd);
    closeSync7(this.fd);
    const inspection = inspectCampaignJournal(this.options.journal.directory), state = this.snapshot();
    this.closed = durable(join8(this.directory, "cash-close.json"), {
      protocol: "openrouter-usd-cash-close-v1",
      currency: "USD",
      configPin: this.configPin,
      cashEventsPin: actualPin(join8(this.directory, "cash-events.jsonl")),
      snapshot: state,
      journalDirectory: this.options.journal.directory,
      journalPrefix: inspection.prefix,
      releasePermitted: inspection.valid && inspection.accountingClosed && state.pendingCount === 0 && state.newUnknownCount === 0,
      scoreCertificate: false,
      invoice: false,
      foreignExchangeConversion: false
    });
    return this.closed;
  }
}
function verifyBenchmarkCashClosure(closePin) {
  const proof = jsonPin(closePin);
  if (proof.protocol !== "openrouter-usd-cash-close-v1")
    throw Error("Expected OpenRouter USD cash closure");
  const config = jsonPin(proof.configPin), eventsRaw = readFileSync6(verifyPin(proof.cashEventsPin));
  const journalConfig = jsonPin(config.journal.configPin);
  validateUsdPrices(config.pricesPin, journalConfig.providerSlug ?? "deepseek");
  verifyPin(config.sourcePin);
  verifyPin(config.journal.sourcePin);
  demand(config.currency === "USD" && config.protocol === "openrouter-usd-cash-config-v1" && Number.isFinite(config.capUsd) && config.capUsd > 0 && resolve8(config.journal.directory) === resolve8(proof.journalDirectory) && journalConfig.currency === "USD" && journalConfig.provider === BENCHMARK_PROVIDER2.kind && journalConfig.campaign === config.runId && journalConfig.priorCampaignCostUpperBoundUsd === 0 && journalConfig.capUsd <= config.capUsd, "usd_close_config");
  const journal = inspectCampaignJournal(proof.journalDirectory);
  demand(journal.valid && journal.accountingClosed && same(journal.prefix, proof.journalPrefix), "usd_close_journal");
  demand(eventsRaw.length <= 256 * 1024 ** 2 && (eventsRaw.length === 0 || eventsRaw.at(-1) === 10), "usd_cash_complete_events");
  let previous = proof.configPin.sha256, seq = 0, starts = 0, known = 0, unknown = 0, unknownCount = 0;
  const active = new Map;
  for (const text of eventsRaw.toString("utf8").trimEnd().split(`
`).filter(Boolean)) {
    const event = JSON.parse(text);
    demand(JSON.stringify(event) === text && Buffer.byteLength(text) <= 65536 && event.index === seq++ && event.previousSha256 === previous && event.protocol === "openrouter-usd-cash-event-v1", "usd_cash_chain");
    previous = hash(text + `
`);
    const { data } = event;
    if (event.kind === "start") {
      const ticket = data.ticket, start = boundStart(proof.journalDirectory, data);
      demand(ticket.requestSeq === starts++ && ticket.currency === "USD" && ticket.reservationUsd === (config.providerKind === "local-mock" ? 0 : start.reservationUsd), "usd_start_reservation");
      const pending = [...active.values()].reduce((sum, row) => sum + (row.dispatchAllowed ? row.reservationUsd : 0), 0);
      demand(ticket.dispatchAllowed === known + unknown + pending + ticket.reservationUsd <= config.capUsd + 0.000000001, "usd_start_budget_replay");
      active.set(ticket.requestSeq, ticket);
    } else {
      demand(event.kind === "finish" && same(active.get(data.ticket.requestSeq), data.ticket) && data.signature === hash(JSON.stringify(data.finish)) && Number.isFinite(data.amountUsd) && data.amountUsd >= 0, "usd_cash_finish_without_start");
      if (data.finish.kind === "journal-finish") {
        const ref = data.finish.journalRef, raw = readFileSync6(join8(proof.journalDirectory, "api-events.jsonl")).subarray(ref.finishOffset, ref.finishEnd);
        const offset = journal.offsets.get(data.ticket.requestSeq);
        demand(offset && offset.offset === ref.finishOffset && offset.offset + offset.bytes === ref.finishEnd && offset.sha256 === ref.finishLineSha256 && hash(raw) === ref.finishLineSha256, "usd_cash_raw_finish");
        const source = JSON.parse(raw.toString("utf8"));
        demand(source.kind === "finish" && source.requestSeq === data.ticket.requestSeq && source.record.route === data.ticket.route && data.phase === (source.record.costBasis === "reservation" ? "unknown" : "known") && data.costBasis === source.record.costBasis && data.generationId === (source.record.requestId ?? null) && data.providerName === (source.record.providerName ?? null) && data.servedModel === (source.record.servedModel ?? null) && (config.providerKind === "local-mock" ? data.amountUsd === 0 : source.record.usdUpperBound === data.amountUsd), "usd_cash_amount_binding");
      } else
        demand(data.finish.kind === "failed-capture" && data.finish.requestSeq === data.ticket.requestSeq && data.phase === "unknown" && data.amountUsd === data.ticket.reservationUsd, "usd_unknown_reservation_binding");
      active.delete(data.ticket.requestSeq);
      if (data.phase === "known")
        known += data.amountUsd;
      else {
        unknown += data.amountUsd;
        unknownCount++;
      }
    }
  }
  demand(active.size === 0 && starts === journal.snapshot.acceptedRequestCount && proof.snapshot.pendingCount === 0 && proof.snapshot.pendingReservationUsd === 0 && proof.snapshot.currency === "USD" && proof.snapshot.runId === config.runId && proof.snapshot.capUsd === config.capUsd && proof.snapshot.newUnknownCount === unknownCount && Math.abs(proof.snapshot.billedUsd - known) < 0.000000001 && Math.abs(proof.snapshot.unknownReservationUsd - unknown) < 0.000000001 && Math.abs(proof.snapshot.exposureUpperBoundUsd - known - unknown) < 0.000000001 && Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 0.000000001 && (config.providerKind === "local-mock" || Math.abs(journal.snapshot.recordedUsageUpperBoundUsd - known - unknown) < 0.000000001), "usd_cash_replay_totals");
  demand(proof.releasePermitted === (unknownCount === 0) && (!(unknownCount || known + unknown > config.capUsd + 0.000000001) || proof.snapshot.poisoned === true), "usd_release_consistency");
  return { proof, config };
}

// scripts/benchmark-campaign/full-f/shared/digitalocean-closed-run-cost.ts
init_paid_resource_proof_v2();

// scripts/benchmark-campaign/full-f/shared/cash-reconciliation.ts
init_paid_resource_proof_v2();
import { createHash as createHash5 } from "crypto";
import { closeSync as closeSync9, existsSync as existsSync5, fsyncSync as fsyncSync8, mkdirSync as mkdirSync7, openSync as openSync9, readFileSync as readFileSync8, readdirSync as readdirSync3, unlinkSync, writeFileSync as writeFileSync4 } from "fs";
import { dirname as dirname3, isAbsolute as isAbsolute4, join as join10, relative as relative4, resolve as resolve10 } from "path";
import { gunzipSync as gunzipSync4 } from "zlib";

// scripts/benchmark-repair/benchmark-usd-cash.ts
init_campaign_journal();
init_cny_cash_shadow_v2();
init_paid_resource_proof_v2();
init_benchmark_provider();
import { closeSync as closeSync8, fsyncSync as fsyncSync7, openSync as openSync8, readFileSync as readFileSync7, readSync as readSync6, statSync as statSync7, writeSync as writeSync5 } from "fs";
import { join as join9, resolve as resolve9 } from "path";
function durable2(path, value) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`), fd = openSync8(path, "wx", 384);
  try {
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync5(fd, raw, at, raw.length - at);
      demand(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync7(fd);
  } finally {
    closeSync8(fd);
  }
  demand(readFileSync7(path).equals(raw), "usd_cash_readback");
  return actualPin(path);
}
function validateUsdPrices2(pin, providerSlug = BENCHMARK_PROVIDER.providerSlug) {
  const data = jsonPin(pin);
  demand(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand(same(data.reservationRates, BENCHMARK_PROVIDER.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand(raw.data?.endpoints?.some((row) => row.provider_name === (providerSlug === "relace" ? "Relace" : "DeepSeek") && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart2(directory, data) {
  const raw = readFileSync7(join9(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand(hash(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route && same(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}
class UsdCash2 {
  options;
  states = new Map;
  tickets = new WeakSet;
  events = [];
  poisonReason;
  closed;
  fd;
  previousHash;
  capUsd;
  bytes = 0;
  directory;
  configPin;
  prices;
  config;
  constructor(options) {
    this.options = options;
    const admission = options.admission;
    demand(options.providerKind === "local-mock" || admission?.currency === "USD", "openrouter_usd_admission_required");
    this.directory = ordinaryDirectory(options.directory);
    this.prices = validateUsdPrices2(options.prices);
    const config = jsonPin(options.journal.configPin);
    demand(config.provider === "openrouter-deepseek" && config.currency === "USD" && config.campaign === options.runId && config.priorCampaignCostUpperBoundUsd === 0, "openrouter_cash_journal_binding");
    this.capUsd = admission?.capUsd ?? config.capUsd;
    demand(Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd, "openrouter_cash_cap_binding");
    this.config = {
      protocol: "openrouter-usd-cash-config-v1",
      runId: options.runId,
      currency: "USD",
      providerKind: options.providerKind,
      capUsd: this.capUsd,
      ownerNonce: admission?.owned.ownerNonce ?? null,
      scope: admission?.scope ?? "local-mock",
      admissionPin: admission?.proofPin ?? null,
      pricesPin: options.prices,
      journal: options.journal,
      sourcePin: actualPin(import.meta.path),
      createdAt: new Date().toISOString(),
      invoice: false,
      foreignExchangeConversion: false
    };
    this.configPin = durable2(join9(this.directory, "cash-config.json"), this.config);
    this.previousHash = this.configPin.sha256;
    this.fd = openSync8(join9(this.directory, "cash-events.jsonl"), "wx+", 384);
    fsyncSync7(this.fd);
    try {
      admission?.registerCash(this.configPin);
    } catch (error) {
      closeSync8(this.fd);
      throw error;
    }
  }
  append(kind, data) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + `
`);
    demand(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync5(this.fd, raw, at, raw.length - at, this.bytes + at);
      demand(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync7(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand(readSync6(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw) && statSync7(join9(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash(raw);
    this.events.push(event);
  }
  snapshot() {
    let known = 0, pending = 0, unknown = 0, pendingCount = 0, unknownCount = 0;
    for (const state of this.states.values()) {
      if (state.phase === "known")
        known += state.amount;
      if (state.phase === "pending") {
        pending += state.ticket.reservationUsd;
        pendingCount++;
      }
      if (state.phase === "unknown") {
        unknown += state.amount;
        unknownCount++;
      }
    }
    return {
      protocol: "openrouter-usd-cash-state-v1",
      currency: "USD",
      runId: this.options.runId,
      capUsd: this.capUsd,
      billedUsd: known,
      pendingReservationUsd: pending,
      unknownReservationUsd: unknown,
      exposureUpperBoundUsd: known + pending + unknown,
      remainingUsd: this.capUsd - known - pending - unknown,
      pendingCount,
      newUnknownCount: unknownCount,
      poisoned: !!this.poisonReason,
      poisonReason: this.poisonReason ?? null,
      invoice: false,
      foreignExchangeConversion: false
    };
  }
  poison(reason) {
    this.poisonReason ??= reason;
  }
  beforeForward(input) {
    demand(!this.closed && !this.poisonReason, "usd_cash_closed_or_poisoned");
    const admission = this.options.admission;
    admission?.validateForwardSource();
    verifyPin(this.options.prices);
    verifyPin(this.config.sourcePin);
    verifyPin(this.options.journal.sourcePin);
    const observed = Date.parse(this.prices.observedAtUtc);
    if (this.options.providerKind === "real-provider")
      demand(Number.isFinite(observed) && Date.now() >= observed && Date.now() - observed <= 86400000, "openrouter_price_expired");
    const j = input.journal.admitted, raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2);
    const inspected = inspectCampaignJournal2(this.options.journal.directory);
    demand(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve9(input.capturedRequest.path) === resolve9(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
    const reservationUsd = this.options.providerKind === "local-mock" ? 0 : j.reservationUsd;
    const permitted = this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 0.000000001;
    const ticket = Object.freeze({
      requestSeq: j.requestSeq,
      route: input.route,
      reservationUsd,
      currency: "USD",
      dispatchAllowed: permitted
    });
    const start = { ticket, requestPin: input.capturedRequest, requestSha256: j.requestSha256, startPrefix: input.journal.startPrefix };
    demand(boundStart2(this.options.journal.directory, start).reservationUsd === j.reservationUsd, "usd_actual_reservation_binding");
    this.append("start", start);
    this.states.set(j.requestSeq, { ticket, phase: permitted ? "pending" : "denied", amount: 0 });
    this.tickets.add(ticket);
    if (!permitted)
      this.poison("usd_envelope_exhausted");
    return { admitted: permitted, ticket, ...!permitted ? { reason: "usd_envelope_exhausted" } : {} };
  }
  finish(given, finish) {
    demand(!this.closed && this.tickets.has(given), "usd_ticket_not_owned");
    const ticket = given, state = this.states.get(ticket.requestSeq);
    const signature = hash(JSON.stringify(finish));
    if (state.signature) {
      demand(state.signature === signature, "usd_duplicate_finish_changed");
      return this.snapshot();
    }
    let phase, amount, receipt;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync7(join9(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand(hash(line) === ref.finishLineSha256, "usd_finish_line_changed");
      const event = JSON.parse(line.toString("utf8"));
      receipt = event.record;
      demand(event.kind === "finish" && event.requestSeq === ticket.requestSeq && receipt.route === ticket.route && inspectCampaignJournal2(this.options.journal.directory).valid, "usd_finish_journal_binding");
      phase = receipt.costBasis === "reservation" ? "unknown" : "known";
      amount = this.options.providerKind === "local-mock" ? 0 : receipt.usdUpperBound;
    } else {
      phase = "unknown";
      amount = ticket.reservationUsd;
      this.poison("usd_failed_capture_unsettled");
    }
    demand(Number.isFinite(amount) && amount >= 0, "usd_finish_amount_invalid");
    this.append("finish", {
      ticket,
      signature,
      phase,
      amountUsd: amount,
      finish,
      costBasis: receipt?.costBasis ?? "reservation",
      generationId: receipt?.requestId ?? null,
      providerName: receipt?.providerName ?? null,
      servedModel: receipt?.servedModel ?? null
    });
    state.phase = phase;
    state.amount = amount;
    state.signature = signature;
    if (phase === "unknown")
      this.poison("usd_unknown_charge");
    if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 0.000000001)
      this.poison("usd_cost_exceeded_cap");
    return this.snapshot();
  }
  close() {
    if (this.closed)
      return this.closed;
    fsyncSync7(this.fd);
    closeSync8(this.fd);
    const inspection = inspectCampaignJournal2(this.options.journal.directory), state = this.snapshot();
    this.closed = durable2(join9(this.directory, "cash-close.json"), {
      protocol: "openrouter-usd-cash-close-v1",
      currency: "USD",
      configPin: this.configPin,
      cashEventsPin: actualPin(join9(this.directory, "cash-events.jsonl")),
      snapshot: state,
      journalDirectory: this.options.journal.directory,
      journalPrefix: inspection.prefix,
      releasePermitted: inspection.valid && inspection.accountingClosed && state.pendingCount === 0 && state.newUnknownCount === 0,
      scoreCertificate: false,
      invoice: false,
      foreignExchangeConversion: false
    });
    return this.closed;
  }
}
function verifyBenchmarkCashClosure2(closePin) {
  const proof = jsonPin(closePin);
  if (proof.protocol !== "openrouter-usd-cash-close-v1")
    throw Error("Expected OpenRouter USD cash closure");
  const config = jsonPin(proof.configPin), eventsRaw = readFileSync7(verifyPin(proof.cashEventsPin));
  const journalConfig = jsonPin(config.journal.configPin);
  validateUsdPrices2(config.pricesPin, journalConfig.providerSlug ?? "deepseek");
  verifyPin(config.sourcePin);
  verifyPin(config.journal.sourcePin);
  demand(config.currency === "USD" && config.protocol === "openrouter-usd-cash-config-v1" && Number.isFinite(config.capUsd) && config.capUsd > 0 && resolve9(config.journal.directory) === resolve9(proof.journalDirectory) && journalConfig.currency === "USD" && journalConfig.provider === BENCHMARK_PROVIDER.kind && journalConfig.campaign === config.runId && journalConfig.priorCampaignCostUpperBoundUsd === 0 && journalConfig.capUsd <= config.capUsd, "usd_close_config");
  const journal = inspectCampaignJournal2(proof.journalDirectory);
  demand(journal.valid && journal.accountingClosed && same(journal.prefix, proof.journalPrefix), "usd_close_journal");
  demand(eventsRaw.length <= 256 * 1024 ** 2 && (eventsRaw.length === 0 || eventsRaw.at(-1) === 10), "usd_cash_complete_events");
  let previous = proof.configPin.sha256, seq = 0, starts = 0, known = 0, unknown = 0, unknownCount = 0;
  const active = new Map;
  for (const text of eventsRaw.toString("utf8").trimEnd().split(`
`).filter(Boolean)) {
    const event = JSON.parse(text);
    demand(JSON.stringify(event) === text && Buffer.byteLength(text) <= 65536 && event.index === seq++ && event.previousSha256 === previous && event.protocol === "openrouter-usd-cash-event-v1", "usd_cash_chain");
    previous = hash(text + `
`);
    const { data } = event;
    if (event.kind === "start") {
      const ticket = data.ticket, start = boundStart2(proof.journalDirectory, data);
      demand(ticket.requestSeq === starts++ && ticket.currency === "USD" && ticket.reservationUsd === (config.providerKind === "local-mock" ? 0 : start.reservationUsd), "usd_start_reservation");
      const pending = [...active.values()].reduce((sum, row) => sum + (row.dispatchAllowed ? row.reservationUsd : 0), 0);
      demand(ticket.dispatchAllowed === known + unknown + pending + ticket.reservationUsd <= config.capUsd + 0.000000001, "usd_start_budget_replay");
      active.set(ticket.requestSeq, ticket);
    } else {
      demand(event.kind === "finish" && same(active.get(data.ticket.requestSeq), data.ticket) && data.signature === hash(JSON.stringify(data.finish)) && Number.isFinite(data.amountUsd) && data.amountUsd >= 0, "usd_cash_finish_without_start");
      if (data.finish.kind === "journal-finish") {
        const ref = data.finish.journalRef, raw = readFileSync7(join9(proof.journalDirectory, "api-events.jsonl")).subarray(ref.finishOffset, ref.finishEnd);
        const offset = journal.offsets.get(data.ticket.requestSeq);
        demand(offset && offset.offset === ref.finishOffset && offset.offset + offset.bytes === ref.finishEnd && offset.sha256 === ref.finishLineSha256 && hash(raw) === ref.finishLineSha256, "usd_cash_raw_finish");
        const source = JSON.parse(raw.toString("utf8"));
        demand(source.kind === "finish" && source.requestSeq === data.ticket.requestSeq && source.record.route === data.ticket.route && data.phase === (source.record.costBasis === "reservation" ? "unknown" : "known") && data.costBasis === source.record.costBasis && data.generationId === (source.record.requestId ?? null) && data.providerName === (source.record.providerName ?? null) && data.servedModel === (source.record.servedModel ?? null) && (config.providerKind === "local-mock" ? data.amountUsd === 0 : source.record.usdUpperBound === data.amountUsd), "usd_cash_amount_binding");
      } else
        demand(data.finish.kind === "failed-capture" && data.finish.requestSeq === data.ticket.requestSeq && data.phase === "unknown" && data.amountUsd === data.ticket.reservationUsd, "usd_unknown_reservation_binding");
      active.delete(data.ticket.requestSeq);
      if (data.phase === "known")
        known += data.amountUsd;
      else {
        unknown += data.amountUsd;
        unknownCount++;
      }
    }
  }
  demand(active.size === 0 && starts === journal.snapshot.acceptedRequestCount && proof.snapshot.pendingCount === 0 && proof.snapshot.pendingReservationUsd === 0 && proof.snapshot.currency === "USD" && proof.snapshot.runId === config.runId && proof.snapshot.capUsd === config.capUsd && proof.snapshot.newUnknownCount === unknownCount && Math.abs(proof.snapshot.billedUsd - known) < 0.000000001 && Math.abs(proof.snapshot.unknownReservationUsd - unknown) < 0.000000001 && Math.abs(proof.snapshot.exposureUpperBoundUsd - known - unknown) < 0.000000001 && Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 0.000000001 && (config.providerKind === "local-mock" || Math.abs(journal.snapshot.recordedUsageUpperBoundUsd - known - unknown) < 0.000000001), "usd_cash_replay_totals");
  demand(proof.releasePermitted === (unknownCount === 0) && (!(unknownCount || known + unknown > config.capUsd + 0.000000001) || proof.snapshot.poisoned === true), "usd_release_consistency");
  return { proof, config };
}

// scripts/benchmark-campaign/full-f/shared/cash-reconciliation.ts
init_campaign_journal();
init_benchmark_provider();
var check2 = (ok, why) => {
  if (!ok)
    throw Error(why);
};
var hash4 = (data) => createHash5("sha256").update(data).digest("hex");
var within = (root, path) => {
  const rel = relative4(resolve10(root), resolve10(path));
  return !!rel && !rel.startsWith("..") && !isAbsolute4(rel);
};
function resolveUnknownReceipt(record, seq, dispatch, response, fenced) {
  check2(fenced, "broker_generation_not_fenced");
  if (dispatch) {
    check2(dispatch.requestSeq === seq && dispatch.requestSha256 === record.requestSha256, "dispatch_request_mismatch");
    check2(response?.requestSeq === seq && response.httpStatus === 200 && response.responsePin, "late_complete_response_required");
    const body2 = jsonPin(response.responsePin);
    check2(typeof body2.id === "string" && body2.id === response.generationId && Number.isFinite(body2.usage?.cost) && body2.usage.cost >= 0 && body2.usage.cost === response.billedUsd, "late_response_cost_or_id_mismatch");
    return {
      requestSeq: seq,
      requestSha256: record.requestSha256,
      classification: "late_complete_provider_receipt",
      actualCostUsd: body2.usage.cost,
      generationId: body2.id,
      providerName: body2.provider,
      servedModel: body2.model,
      responsePin: response.responsePin,
      protocolFault: officialOpenRouterFault(body2),
      scoreCertificate: false
    };
  }
  check2(!response && record.httpStatus === 503 && record.responseFile, "unforwarded_rejection_evidence_required");
  const zipped = readFileSync8(record.responseFile), raw = gunzipSync4(zipped);
  check2(hash4(zipped) === record.responseCompressedSha256 && hash4(raw) === record.responseSha256, "local_rejection_bytes_changed");
  const body = JSON.parse(raw.toString("utf8"));
  check2(!body.id && !body.usage && !body.choices && (body.error?.code === "bench_broker_stopped" || body.error?.message === "Broker stopped"), "not_a_verified_local_broker_rejection");
  return {
    requestSeq: seq,
    requestSha256: record.requestSha256,
    classification: "fenced_broker_never_dispatched",
    actualCostUsd: 0,
    generationId: null,
    localResponsePin: actualPin(record.responseFile),
    scoreCertificate: false
  };
}
function evaluate2(scope) {
  const h = jsonPin(scope.healthPin), parent = jsonPin(scope.parentAdmissionPin), archive = jsonPin(scope.sourceArchivePin);
  check2(h.protocol === "full-f-broker-status-v1" && h.localMock === false && h.healthy === false && h.stopReason && h.lanes.length > 0 && h.activeRequests === 0 && h.queuedRequests === 0 && Object.keys(h.resources).length === 0, "broker_not_drained");
  check2(parent.protocol === "openrouter-usd-admission-v1" && parent.currency === "USD" && parent.family === "four-bench-full-f-v1" && same(parent.owned, h.canonicalOwner) && parent.owned.runId === h.runId && parent.owned.pid === h.pid && parent.sourcePins.length >= 10 && parent.owned.entry === join10(resolve10(scope.root), "scripts/benchmark-campaign/full-f/shared/full-f-broker.ts"), "parent_identity_mismatch");
  for (const pin of parent.sourcePins) {
    const row = archive.pins.find((item) => same(item.original, pin));
    check2(row && row.archived.sha256 === pin.sha256 && row.archived.bytes === pin.bytes, "missing_original_source_archive");
    verifyPin(row.archived);
  }
  const eventRows = scope.eventPins.map((pin) => ({ pin, value: jsonPin(pin) }));
  check2(eventRows.every((row, index) => row.value.index === index && row.value.localMock === false), "incomplete_broker_event_prefix");
  const events = eventRows.map((row) => row.value);
  check2(events.some((event) => event.kind === "stop"), "missing_broker_stop");
  const acquired = eventRows.find((row) => row.value.kind === "canonical-owner-acquired");
  check2(acquired && same(acquired.value.admissionPin, scope.parentAdmissionPin), "wrong_parent_event");
  const dispatches = new Map, responses = new Map, generations = new Set;
  let rawCostUsd = 0;
  for (const event of events) {
    if (!["dispatch", "response"].includes(event.kind))
      continue;
    check2(h.lanes.some((lane) => lane.runId === event.runId), "dispatch_outside_registered_lanes");
    const key = `${event.runId}/${event.requestSeq}`;
    if (event.kind === "dispatch") {
      check2(!dispatches.has(key), "duplicate_dispatch");
      dispatches.set(key, event);
    } else {
      check2(dispatches.has(key) && !responses.has(key), "response_without_unique_dispatch");
      responses.set(key, event);
      const body = jsonPin(event.responsePin);
      if (event.httpStatus === 200) {
        check2(body.id === event.generationId && typeof body.id === "string" && !generations.has(body.id) && Number.isFinite(body.usage?.cost) && body.usage.cost >= 0 && body.usage.cost === event.billedUsd, "invalid_or_duplicate_billed_generation");
        generations.add(body.id);
        rawCostUsd += body.usage.cost;
      } else
        check2(event.explicitRateRejection === true && event.generationId === null && !body.usage && !body.choices, "unsettled_real_provider_response");
    }
  }
  check2(dispatches.size === responses.size, "provider_request_still_unsettled");
  const lanes = [];
  let unknownCount = 0;
  for (const lane of h.lanes) {
    check2(["chembench", "chemiq", "skillsbench", "terminal-bench"].includes(lane.slug) && within(join10(scope.root, "docs/repair-2026-10-10/full-f-rerun", lane.slug), lane.output), "unexpected_lane_scope");
    const cashRow = scope.cashClosures.find((row) => row.runId === lane.runId);
    check2(cashRow && within(lane.output, cashRow.closePin.path), "missing_lane_cash_closure");
    const closed = verifyBenchmarkCashClosure2(cashRow.closePin), proof = closed.proof, config = closed.config;
    const registered = events.find((event) => event.kind === "cash-registered" && event.runId === lane.runId);
    const created = events.find((event) => event.kind === "lane-created" && event.runId === lane.runId);
    check2(registered && created && same(registered.cashPin, proof.configPin) && same(created.admissionPin, config.admissionPin) && config.ownerNonce === parent.owned.ownerNonce && config.capUsd === lane.capUsd && config.providerKind === "real-provider", "cash_parent_registration_mismatch");
    const journal = inspectCampaignJournal2(config.journal.directory);
    check2(journal.valid && journal.accountingClosed && journal.snapshot?.active.length === 0, "journal_not_closed");
    const finished = readFileSync8(join10(config.journal.directory, "api-events.jsonl"), "utf8").trimEnd().split(`
`).filter(Boolean).map((line) => JSON.parse(line)).filter((event) => event.kind === "finish");
    const resolutions = [];
    for (const event of finished) {
      const key = `${lane.runId}/${event.requestSeq}`, record = event.record, dispatch = dispatches.get(key), response = responses.get(key);
      if (record.costBasis === "reservation") {
        if (!dispatch)
          check2(Date.parse(record.finishedAt) >= Date.parse(events.find((entry) => entry.kind === "stop").atUtc), "local_rejection_before_broker_stop");
        resolutions.push(resolveUnknownReceipt(record, event.requestSeq, dispatch, response, true));
      } else if (record.costBasis === "provider_reported_usd") {
        check2(dispatch?.requestSha256 === record.requestSha256 && response?.generationId === record.requestId && response.billedUsd === record.usdUpperBound, "known_receipt_broker_mismatch");
      } else
        check2(record.usdUpperBound === 0 && (!dispatch || response?.explicitRateRejection === true), "unproven_original_zero");
    }
    check2(resolutions.length === proof.snapshot.newUnknownCount && [...dispatches.keys()].filter((key) => key.startsWith(lane.runId + "/")).length === lane.dispatched, "lane_dispatch_or_unknown_count_mismatch");
    unknownCount += resolutions.length;
    const recoveredCostUsd = resolutions.reduce((sum, row) => sum + row.actualCostUsd, 0);
    lanes.push({
      slug: lane.slug,
      runId: lane.runId,
      originalCashClosePin: cashRow.closePin,
      originalReleasePermitted: proof.releasePermitted,
      originalUnknownCount: proof.snapshot.newUnknownCount,
      originalUnknownReservationUsd: proof.snapshot.unknownReservationUsd,
      originalKnownBilledUsd: proof.snapshot.billedUsd,
      resolutions,
      recoveredCostUsd,
      effectiveBilledUsd: proof.snapshot.billedUsd + recoveredCostUsd,
      remainingUnknownCostCount: 0,
      originalJournalAndCashUnmodified: true,
      scoreCertificate: false
    });
  }
  check2(lanes.length === scope.cashClosures.length, "extra_cash_closures");
  const effectiveBilledUsd = lanes.reduce((sum, lane) => sum + lane.effectiveBilledUsd, 0);
  check2(Math.abs(effectiveBilledUsd - rawCostUsd) < 0.000000001 && effectiveBilledUsd <= parent.capUsd + 0.000000001, "reconciled_cost_does_not_match_all_real_dispatches");
  return {
    owner: parent.owned,
    brokerRunId: h.runId,
    lanes,
    originalUnknownCostCount: unknownCount,
    remainingUnknownCostCount: 0,
    effectiveBilledUsd,
    rawProviderBilledUsd: rawCostUsd,
    modelCalls: 0,
    scoreCertificate: false
  };
}
function verifyReconciliation(pin) {
  const report = jsonPin(pin);
  check2(report.protocol === "full-f-supplemental-cash-reconciliation-v1", "wrong_reconciliation_protocol");
  check2(same(report.verifierSourcePin, actualPin(import.meta.path)), "reconciliation_verifier_source_changed");
  const checked = evaluate2(report.scope);
  check2(same(checked, report.result), "reconciliation_report_changed");
  return checked;
}
if (false) {}

// scripts/benchmark-campaign/full-f/shared/digitalocean-closed-run-cost.ts
var cache = new Map;
function inspectFullFClosedCash(root, pin) {
  const verified = verifyBenchmarkCashClosure(pin), snapshot = verified.proof.snapshot;
  const control = JSON.parse(readFileSync9(join11(root, "docs/repair-2026-10-10/full-f-rerun/control.json"), "utf8"));
  let { billedUsd, newUnknownCount: unknownCostCount, unknownReservationUsd } = snapshot;
  if (unknownCostCount && control.legacyReconciliationPin) {
    const proof = control.legacyReconciliationPin, key = proof.path + ":" + proof.sha256;
    let report = cache.get(key);
    if (!report) {
      report = verifyReconciliation(proof);
      cache.set(key, report);
    }
    const resolved = report.lanes.find((lane) => same(lane.originalCashClosePin, pin));
    if (resolved) {
      billedUsd = resolved.effectiveBilledUsd;
      unknownCostCount = resolved.remainingUnknownCostCount;
      unknownReservationUsd = 0;
    }
  }
  if (unknownCostCount && control.costPolicy?.mode !== "record_and_continue")
    throw Error("Previous cash requires continuation authorization");
  return {
    ...verified,
    billedUsd,
    unknownCostCount,
    unknownReservationUsd,
    accountingClosed: true,
    financiallyResolved: unknownCostCount === 0,
    originalReleasePermitted: verified.proof.releasePermitted,
    rawEvidenceUnmodified: true,
    scoreCertificate: false
  };
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/forward_guard.ts
init_paid_resource_proof_v2();
import { execFile } from "child_process";
import { join as join12 } from "path";
var script = join12(import.meta.dir, "owner_preflight.py");
var sourcePin = actualPin(script);
var wrapperPin = actualPin(join12(import.meta.dir, "activation_guard.py"));
async function beforePipelineForward() {
  verifyPin(sourcePin);
  verifyPin(wrapperPin);
  if (process.env.NOVAEVE_RESOURCE_MEMORY_MB !== "24576" || process.env.NOVAEVE_RESOURCE_GROWTH_BYTES !== "32212254720" || process.env.NOVAEVE_RESOURCE_LEASE_PID !== String(process.pid) || process.env.NOVAEVE_RESOURCE_PARENT_PID !== String(process.pid) || !process.env.NOVAEVE_RESOURCE_TOKEN)
    throw Error("actual_original_pipeline_forward_owner_required");
  return new Promise((resolve11, reject) => {
    execFile("D:/ProgramData/anaconda3/python.exe", ["-B", script, "--forward"], { cwd: "F:/git/TgEngin-handoff-2026-10-07/TgEngin", timeout: 45000, maxBuffer: 16384, windowsHide: true }, (error, stdout) => {
      if (error) {
        reject(Error("actual_pipeline_before_forward_guard_rejected"));
        return;
      }
      try {
        const result = JSON.parse(stdout);
        if (!result.passed || !result.actualLeaseVerified || result.mode !== "forward" || result.providerTransportInvoked !== false)
          throw Error("actual_pipeline_forward_receipt_required");
        resolve11();
      } catch (e) {
        reject(e);
      }
    });
  });
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/resource_lease.ts
import { readFileSync as readFileSync12 } from "fs";
import { join as join15 } from "path";

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/broker/adopted-consumer-guard-v48.ts
init_paid_resource_proof_v2();
import { readFileSync as readFileSync11 } from "fs";
import { resolve as resolve12, join as join14 } from "path";

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/broker/sign-adoption-v48.ts
import { readFileSync as readFileSync10 } from "fs";
import { resolve as resolve11, join as join13 } from "path";
import { verify } from "crypto";
var root = resolve11(import.meta.dir, "../../../../..");
var base = join13(root, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator");
function verifyAdoptionEnvelope(envelope, protocol = "novaeve-root-reviewed-broker-adoption-v48") {
  if (envelope.protocol !== "novaeve-root-signed-adoption-v48" || envelope.plan?.protocol !== protocol || envelope.plan.rootReviewed !== true || !verify(null, Buffer.from(JSON.stringify(envelope.plan)), readFileSync10(join13(base, "review-authority.public.pem"), "utf8"), Buffer.from(envelope.signature ?? "", "base64")))
    throw Error("actual_root_adoption_signature_required");
  return envelope.plan;
}
if (false) {}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/broker/adopted-consumer-guard-v48.ts
var demand4 = (v, c) => {
  if (!v)
    throw Error(c);
};
function assertLiveAdoptionSnapshot(h, connection, proof, owner) {
  demand4(h.healthy && h.pid === connection.pid && h.runId === connection.runId && h.targetMax === 16 && Number.isInteger(h.maxInFlight) && h.maxInFlight >= 1 && h.maxInFlight <= 16 && h.adoption?.singleResourcePool === true && h.adoption.liveExecutorPid === h.pid && same(h.adoption.signedAdoptionPlanPin, connection.adoption.signedAdoptionPlanPin) && same(h.canonicalOwner, owner), "actual_live_executor_and_historical_owner_required");
  demand4(h.allocation.capUsd === proof.originalCapUsd && h.allocation.allocatedUsd >= proof.minimumRetainedAllocationUsd && h.allocation.allocatedUsd <= proof.originalCapUsd, "original_budget_carry_required");
  const used = h.resourceSlots.filter((r) => r.kind === "heavy-container").reduce((n, r) => n + r.slots, 0);
  demand4(used + h.availableResourceSlots["heavy-container"] === 16, "single_sixteen_pool_required");
}
async function verifyAdoptedConnection(connection, initialPublication = false) {
  const root2 = resolve12(import.meta.dir, "../../../../.."), home = join14(root2, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013");
  demand4(connection.endpoint === "http://127.0.0.1:17895" && connection.pid > 0 && connection.adoption?.liveExecutorPid === connection.pid, "actual_adopted_connection_required");
  const signedPin = connection.adoption.signedAdoptionPlanPin;
  verifyPin(signedPin);
  const plan = verifyAdoptionEnvelope(jsonPin(signedPin));
  for (const p of plan.sourcePins)
    verifyPin(p);
  verifyPin(plan.restartProofPin);
  verifyPin(plan.previousAdoptionGuardPin);
  const restart = jsonPin(plan.restartProofPin);
  for (const p of restart.durablePins)
    verifyPin(p);
  const proof = jsonPin(plan.rehydrateProofPin);
  demand4(proof.historyUnknownCount === 42 && proof.originalCapUsd === 418.777826378, "original_union42_cap_required");
  for (const p of [proof.parentPin, proof.canonicalLockPin, proof.allocationPin, proof.originalGlobalDelegationGuardPin, proof.historyPin])
    verifyPin(p);
  const owner = jsonPin(proof.canonicalLockPin), parent = jsonPin(proof.parentPin);
  demand4(same(owner, parent.owned), "original_owner_parent_identity");
  const healths = await Promise.all([17895, 17889].map(async (port) => {
    const r = await fetch("http://127.0.0.1:" + port + "/health", { signal: AbortSignal.timeout(5000) });
    demand4(r.ok, "adopted_health_http");
    return r.json();
  }));
  for (const h of healths)
    assertLiveAdoptionSnapshot(h, connection, proof, owner);
  demand4(healths.every((h) => JSON.stringify(h.adoption.resourceEndpoints) === "[17889,17895]" && h.adoption.protocol === "novaeve-truthful-broker-adoption-v48"), "signed_same_executor_shared_map_identity");
  if (initialPublication) {
    const held = healths[0].resourceSlots.filter((r) => r.adoptedOrphanHold);
    demand4(held.length === 3 && held.every((r) => proof.resourceHoldRows.some((p) => p.pid === r.pid && p.slots === r.slots)), "three_original_holds_publication_required");
  }
  return { connection, health: healths[0], plan, proof, owner, sourcePin: actualPin(import.meta.path) };
}
async function verifyAdoptedActivation(path) {
  const activation = JSON.parse(readFileSync11(path, "utf8"));
  demand4(activation.active && activation.activated && activation.adoption?.protocol === "novaeve-truthful-broker-adoption-v48" && !activation.delegation, "new_activation_no_live_old_delegation");
  const control = jsonPin(activation.controlPin);
  demand4(control.paidReady && control.broker.pid === activation.adoption.liveExecutorPid, "actual_control_binding");
  verifyPin(activation.consumerGuardPin);
  return verifyAdoptedConnection(control.broker);
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/resource_lease.ts
async function boundConnection(root2) {
  const ap = join15(root2, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/activation-adopted-v48.json");
  const checked = await verifyAdoptedActivation(ap), a = JSON.parse(readFileSync12(ap, "utf8"));
  if (a.dockerHost !== "tcp://127.0.0.1:18750" || a.totalConcurrency !== 16 || a.brokerEndpoint !== checked.connection.endpoint || a.runId !== checked.connection.runId)
    throw Error("pipeline_actual_adopted_epoch");
  await verifyAdoptedConnection(checked.connection);
  process.env.NOVAEVE_ACTIVATION_PATH = ap;
  process.env.NOVAEVE_BROKER_CONTROL_PATH = a.brokerControlPath;
  return checked.connection;
}
async function acquireResource(root2) {
  const c = await boundConnection(root2), body = { slug: "terminal-bench", kind: "heavy-container", pid: process.pid, slots: 1, memoryMb: 24576, plannedGrowthBytes: 32212254720 };
  async function rpc2(path, value) {
    const r = await fetch(c.endpoint + path, { method: "POST", headers: { authorization: "Bearer " + c.accessToken, "content-type": "application/json" }, body: JSON.stringify(value), signal: AbortSignal.timeout(30000) });
    const x = await r.json();
    if (!r.ok)
      throw Error(x.reason ?? x.error ?? "resource_failed");
    return x;
  }
  const claim = await rpc2("/resource/acquire", body);
  try {
    const { health: h } = await verifyAdoptedConnection(c);
    const held = h.resourceSlots.filter((x) => x.kind === "heavy-container" && x.pid === process.pid && x.slug === "terminal-bench" && x.token === claim.token && x.memoryMb >= 24576 && x.plannedGrowthBytes >= 32212254720);
    if (held.length !== 1)
      throw Error("pipeline_actual_held_token_required");
  } catch (e) {
    await rpc2("/resource/release", { ...body, token: claim.token });
    throw e;
  }
  process.env.NOVAEVE_RESOURCE_PARENT_PID = String(process.pid);
  process.env.NOVAEVE_RESOURCE_LEASE_PID = String(process.pid);
  process.env.NOVAEVE_RESOURCE_MEMORY_MB = "24576";
  process.env.NOVAEVE_RESOURCE_GROWTH_BYTES = "32212254720";
  process.env.NOVAEVE_RESOURCE_BENCH = "terminal-bench";
  process.env.NOVAEVE_RESOURCE_TOKEN = claim.token;
  let released = false;
  return { async release() {
    if (released)
      throw Error("resource_already_released");
    await rpc2("/resource/release", { ...body, token: claim.token });
    released = true;
  } };
}

// scripts/benchmark-campaign/full-f/terminal-bench/tool-unit-budget.next.ts
import { writeFileSync as writeFileSync6 } from "fs";
async function alignToolUnitBudget(machine, declaredToolMs, proofPath) {
  if (!Number.isSafeInteger(declaredToolMs) || declaredToolMs <= 0)
    throw Error("declared_tool_envelope_required");
  const before = await machine.api("POST", "/query", { sql: "select name,expect_ms from handle where name='fn:unit.tools'" });
  await machine.api("POST", "/exec", { sql: "update handle set expect_ms=:ms where name='fn:unit.tools'", params: { ms: declaredToolMs } });
  const after = await machine.api("POST", "/query", { sql: "select name,expect_ms from handle where name='fn:unit.tools'" });
  const rows = Array.isArray(after) ? after : after.rows;
  if (!Array.isArray(rows) || rows.length !== 1 || Number(rows[0].expect_ms) !== declaredToolMs)
    throw Error("tool_unit_envelope_readback");
  const proof = { atUtc: new Date().toISOString(), before, after, declaredToolMs, isolatedEngineOnly: true, taskSolveSecondsUnchanged: true, individualToolTimeoutUnchanged: true, modelBudgetUnchanged: true };
  if (proofPath)
    writeFileSync6(proofPath, JSON.stringify(proof, null, 2) + `
`, { flag: "wx" });
  return proof;
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/campaign.ts
import { randomBytes as randomBytes6 } from "crypto";
init_candidate();
import { mkdirSync as mkdirSync15, readFileSync as readFileSync20 } from "fs";
import { join as join34, resolve as resolve29 } from "path";
import { Database } from "bun:sqlite";

// scripts/benchmark-repair/campaign-contract-http-v5.ts
init_registry();
init_run();
init_spec();
import { createHash as createHash6 } from "crypto";
var PEAK_RATES2 = Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 });
var object2 = (value) => value !== null && typeof value === "object" && !Array.isArray(value) ? value : undefined;
var count2 = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
function usageCounts2(value) {
  const usage = object2(value);
  const input = usage?.prompt_tokens, output = usage?.completion_tokens;
  const cached = usage?.prompt_cache_hit_tokens ?? object2(usage?.prompt_tokens_details)?.cached_tokens ?? 0;
  if (!count2(input) || !count2(output) || !count2(cached) || cached > input)
    throw new Error("InvalidProviderTokenUsage");
  return { input, output, cached };
}
function validTokenUsage2(value) {
  try {
    usageCounts2(value);
    return true;
  } catch {
    return false;
  }
}
function isNonGenerationRateRejection2(call) {
  return call.nonGenerationRejection === "upstream_rate_limit" && call.httpStatus === 429 && call.providerAttempted === true && call.costBasis === "known_uncharged" && call.usdUpperBound === 0 && !call.usage && !call.requestId && !call.fault && !!call.finishedAt;
}
function classifyGeneration(input) {
  const runtime = object2(input.runtimeVerdict);
  const runtimeOutcome = String(runtime?.outcome ?? "unaided_generated");
  const result = (valid, kind, outcome, why) => ({ valid, kind, outcome, why, runtimeOutcome, runtimeVerdict: structuredClone(input.runtimeVerdict) });
  if (["finalization_pending", "finalization_error"].includes(runtimeOutcome) || input.state !== undefined && !["done", "failed"].includes(input.state))
    return result(false, "pending", "pending_finalization", "generation or finalization has not finished");
  if (["provider_error", "grader_error"].includes(runtimeOutcome))
    return result(false, "infrastructure_error", runtimeOutcome, String(runtime?.why ?? runtimeOutcome));
  const stuck = input.trace.some((row) => {
    if (row.role !== "system" || row.kind !== "inject")
      return false;
    try {
      return Object.hasOwn(object2(JSON.parse(String(row.body))) ?? {}, "stuck");
    } catch {
      return false;
    }
  });
  if (stuck)
    return result(false, "infrastructure_error", "kernel_stuck", "the runtime recorded a failed execution unit");
  if (!input.calls.length)
    return result(false, "infrastructure_error", "missing_api_receipt", "no model request receipt was recorded");
  if (input.calls.some((call) => call.completionValid === false || call.completionFault))
    return result(false, "infrastructure_error", "malformed_completion", "a HTTP success did not contain a valid completion");
  if (input.calls.some((call) => !isNonGenerationRateRejection2(call) && (call.fault || call.httpStatus !== 200 || !call.finishedAt || !validTokenUsage2(call.usage))))
    return result(false, "infrastructure_error", "invalid_api_receipt", "a model call failed, remained pending, or lacks valid token usage");
  if (runtime?.valid === false && !["task_timeout", "no_candidate"].includes(runtimeOutcome))
    return result(false, "infrastructure_error", "invalid_runtime", "the runtime explicitly rejected the validity of its receipt");
  if (input.candidate === undefined) {
    const exhausted = runtimeOutcome === "task_timeout" || /over solve_seconds=/.test(String(runtime?.why ?? ""));
    return result(true, "experimental_failure", exhausted ? "budget_exhausted" : "no_candidate", exhausted ? "the declared solving budget was exhausted without a hand-in" : "the model did not hand in a candidate");
  }
  return result(true, "candidate", "candidate", "");
}
async function gradeFixedCandidate(input) {
  const candidateSha256 = createHash6("sha256").update(input.candidate ?? "").digest("hex");
  const no = (valid, outcome, why) => ({ valid, passed: false, outcome, why, candidateSha256, nodes: {} });
  if (input.expectedCandidateSha256 !== undefined && input.expectedCandidateSha256 !== candidateSha256)
    return no(false, "candidate_changed", "the frozen candidate digest does not match");
  if (!input.generation.valid)
    return no(false, input.generation.outcome, input.generation.why);
  if (input.candidate === undefined)
    return no(true, input.generation.outcome, input.generation.why);
  try {
    const objective = parseObjective(input.objective);
    const registry = new Registry;
    for (const node of objective.nodes)
      registry.adopt(node.handle, input.timeoutMs ?? 120000, async (arg) => {
        const url = new URL(node.handle);
        if (!["http:", "https:"].includes(url.protocol))
          throw new Error("Campaign graders must be HTTP handles");
        const response = await graderFetch(node.handle, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(arg), signal: AbortSignal.timeout(input.timeoutMs ?? 120000), ...{ timeout: false } });
        if (!response.ok)
          throw new Error(`${node.name}: grader HTTP ${response.status}`);
        return await response.json();
      });
    const verdict = await evaluate(objective, registry, candidateInput(input.task, input.candidate));
    const nodes = Object.fromEntries(verdict.trace.map((node) => [node.node, { value: node.value, valid: !node.error, ...node.error ? { error: node.error } : {}, ...node.note ? { note: node.note } : {} }]));
    return { valid: verdict.valid, passed: verdict.valid && verdict.pass === 1, outcome: verdict.outcome, why: verdict.why, candidateSha256, nodes, verdict };
  } catch (error) {
    return no(false, "grader_error", error instanceof Error ? error.message : "grading failed");
  }
}
function campaignComplete(planned, records) {
  if (!Number.isSafeInteger(planned) || planned < 1 || records.length !== planned)
    return false;
  const seen = new Set;
  for (const record of records) {
    if (!count2(record.index) || record.index >= planned || seen.has(record.index))
      return false;
    seen.add(record.index);
    const accepted = record.acceptance;
    if (accepted?.valid !== true || typeof accepted.passed !== "boolean")
      return false;
    if (!["passed", "rejected", "budget_exhausted", "no_candidate"].includes(String(accepted.outcome)) || accepted.passed !== (accepted.outcome === "passed"))
      return false;
  }
  return true;
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/campaign.ts
init_paid_resource_proof_v2();

// scripts/terminal-bench-repair/tb12-v2/paid_admission.ts
import { randomBytes as randomBytes3 } from "crypto";
import { closeSync as closeSync12, fsyncSync as fsyncSync11, mkdirSync as mkdirSync9, openSync as openSync12, readFileSync as readFileSync15, renameSync as renameSync3, statfsSync, unlinkSync as unlinkSync2, writeFileSync as writeFileSync8 } from "fs";
import { dirname as dirname10, join as join26, resolve as resolve23 } from "path";
init_paid_resource_proof_v2();
await __promiseAll([
  init_paid_resource_admission_v2(),
  init_jpg_paid_resource_admission_v1(),
  init_jpg_D_paid_resource_admission_v1(),
  init_financial_interruption_release()
]);

// scripts/terminal-bench-repair/tb12-v2/peak_cash_shadow.ts
init_campaign_journal();
import { closeSync as closeSync11, existsSync as existsSync7, fsyncSync as fsyncSync10, openSync as openSync11, readFileSync as readFileSync14, readSync as readSync8, statSync as statSync9, writeFileSync as writeFileSync7, writeSync as writeSync7 } from "fs";
import { join as join25, resolve as resolve22 } from "path";
init_paid_resource_proof_v2();
var SELF7 = actualPin(import.meta.path);
var PROOF_SOURCE2 = actualPin(join25(import.meta.dir, "../../benchmark-repair/paid-resource-proof-v2.ts"));

class CashWriter2 {
  directory;
  hook;
  path;
  configPin;
  fd;
  prefix;
  failed = false;
  closed = false;
  constructor(directory, config, hook) {
    this.directory = directory;
    this.hook = hook;
    const path = join25(directory, "cash-config.json"), raw = Buffer.from(JSON.stringify(config) + `
`), fd = openSync11(path, "wx", 384);
    try {
      writeFileSync7(fd, raw);
      fsyncSync10(fd);
    } finally {
      closeSync11(fd);
    }
    demand(readFileSync14(path).equals(raw), "cash_config_readback");
    this.configPin = actualPin(path);
    this.path = join25(directory, "cash-events.jsonl");
    this.fd = openSync11(this.path, "wx+", 384);
    fsyncSync10(this.fd);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configPin.sha256 };
  }
  append(kind, data) {
    demand(!this.failed && !this.closed, "cash_writer_unclosed_fault");
    const event = { protocol: "cny-shadow-event-v2", eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, data }, raw = Buffer.from(JSON.stringify(event) + `
`);
    demand(raw.length <= 65536 && this.prefix.bytes + raw.length <= 256 * 1024 ** 2, "cash_metadata_bound");
    const offset = this.prefix.bytes;
    try {
      this.hook?.("cash_write");
      let n = 0;
      while (n < raw.length) {
        const got = writeSync7(this.fd, raw, n, raw.length - n, offset + n);
        demand(got > 0, "cash_short_write");
        n += got;
      }
      this.hook?.("cash_fsync");
      fsyncSync10(this.fd);
      this.hook?.("cash_readback");
      const read = Buffer.alloc(raw.length);
      demand(readSync8(this.fd, read, 0, read.length, offset) === read.length && read.equals(raw) && statSync9(this.path).size === offset + raw.length, "cash_event_readback");
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash(raw) };
      return { ...this.prefix };
    } catch (error) {
      this.failed = true;
      throw error;
    }
  }
  snapshot() {
    return { ...this.prefix };
  }
  fault() {
    return this.failed;
  }
  close() {
    if (this.closed)
      return;
    try {
      fsyncSync10(this.fd);
    } finally {
      closeSync11(this.fd);
      this.closed = true;
    }
  }
}
function createCnyCashShadow2(options) {
  return new CnyCashShadow2(options);
}

class CnyCashShadow2 {
  options;
  directory;
  writer;
  binding;
  clock;
  states = new Map;
  ticketStates = new WeakMap;
  poisonReason;
  clockWall;
  clockMono;
  closedPin;
  nextSeq = 0;
  prices;
  config;
  configPin;
  constructor(given) {
    const options = Object.freeze({ ...given, prices: Object.freeze({ ...given.prices }), journal: Object.freeze({ ...given.journal, configPin: Object.freeze({ ...given.journal.configPin }), sourcePin: Object.freeze({ ...given.journal.sourcePin }) }) });
    this.options = options;
    demand(options.providerKind === "local-mock" || options.admission, "real_provider_admission_required");
    demand(options.providerKind !== "local-mock" || !options.admission || options.admission.scope === "f-fixture", "production_admission_cannot_zero_mock");
    if (options.fixtureIo)
      demand(options.admission?.scope === "f-fixture", "cash_fault_hooks_fixture_only");
    this.directory = ordinaryDirectory(options.directory);
    this.clock = options.admission?.clock ?? options.clock ?? REAL_CLOCK;
    this.prices = validatePrices(options.prices);
    this.binding = new JournalBinding(resolve22(options.journal.directory), options.journal.configPin, options.journal.sourcePin);
    demand(this.binding.config.campaign === options.runId, "cash_journal_run_binding");
    this.config = { protocol: "cny-shadow-config-v2", pricingMode: "published-peak-conservative-upper-bound", runId: options.runId, providerKind: options.providerKind, scope: options.admission?.scope ?? "local-mock", ownerNonce: options.admission?.owned.ownerNonce ?? null, admissionPin: options.admission?.proofPin ?? null, envelopeNanoCny: (options.admission?.envelopeNanoCny ?? 0n).toString(), carryNanoCny: (options.admission?.carryNanoCny ?? 0n).toString(), pricesPin: options.prices, journalDirectory: resolve22(options.journal.directory), journalConfigPin: options.journal.configPin, journalSourcePin: options.journal.sourcePin, cashSourcePins: [SELF7, PROOF_SOURCE2], createdAt: new Date(this.clock.wallUnixMs()).toISOString(), priceTTL: "real-beforeForward24h", moneyUnit: "nanoCNY", invoice: false, foreignExchangeConversion: false };
    this.writer = new CashWriter2(this.directory, this.config, options.fixtureIo);
    this.configPin = this.writer.configPin;
    try {
      options.admission?.registerCash(this.configPin);
    } catch (error) {
      this.writer.close();
      throw error;
    }
  }
  clockNow() {
    const wall = this.clock.wallUnixMs(), mono = this.clock.monotonicNs();
    const fault = !Number.isFinite(wall) || this.clockWall !== undefined && wall < this.clockWall || this.clockMono !== undefined && mono < this.clockMono;
    if (fault)
      this.poisonReason ??= "clock_rollback_or_unknown";
    this.clockWall = wall;
    this.clockMono = mono;
    return { wall, mono, fault };
  }
  count() {
    let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
    for (const s of this.states.values()) {
      if (s.phase === "known")
        known += s.amount;
      else if (s.phase === "unknown") {
        unknown += s.amount;
        unknownCount++;
      } else if (s.phase === "pending" || s.phase === "denied") {
        pending += s.reservation;
        pendingCount++;
      }
    }
    return { known, pending, unknown, pendingCount, unknownCount };
  }
  snapshot() {
    const t = this.count(), envelope = this.options.admission?.envelopeNanoCny ?? 0n;
    return { protocol: "cny-shadow-cash-v2", runId: this.options.runId, currency: "CNY", providerKind: this.options.providerKind, carriedOriginalUnknownNanoCny: this.config.carryNanoCny, newKnownEstimatedNanoCny: t.known.toString(), newPendingPeakNanoCny: t.pending.toString(), newUnknownPeakNanoCny: t.unknown.toString(), newExposureNanoCny: (t.known + t.pending + t.unknown).toString(), remainingNewEnvelopeNanoCny: (envelope - t.known - t.pending - t.unknown).toString(), pendingCount: t.pendingCount, newUnknownCount: t.unknownCount, poisoned: !!this.poisonReason, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
  }
  beforeForward(input) {
    demand(!this.closedPin && !this.writer.fault(), "cash_closed_or_faulted");
    const j = input.journal.admitted;
    demand(j.admitted === true && integer(j.requestSeq) && j.requestSeq === this.nextSeq && !this.states.has(j.requestSeq), "cash_request_sequence");
    const start = this.binding.start(j.requestSeq, input.journal.startPrefix), raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2), v = requestValues(raw);
    demand(Buffer.from(input.rawRequest).equals(raw) && resolve22(input.capturedRequest.path) === resolve22(j.requestFile) && start.requestFile === j.requestFile && start.requestSha256 === j.requestSha256 && start.requestCompressedSha256 === input.capturedRequest.sha256 && start.requestBytes === raw.length && start.route === input.route && start.providerAttempted === false && Math.abs(start.reservationUsd - j.reservationUsd) < 0.000000001, "cash_actual_admission_binding");
    demand(Math.abs(j.reservationUsd - (v.inputUpper * 0.3 + v.output * 1.2) / 1e6) < 0.000000001, "legacy_usd_reservation_binding");
    const checkpoint = jsonPin(actualPin(join25(this.binding.directory, "api-state.json")));
    demand(checkpoint.configSha256 === this.binding.configSha && !existsSync7(join25(this.binding.directory, "journal-error.json")), "journal_checkpoint_unacknowledged");
    this.binding.consume(checkpoint.durablePrefix);
    for (const path of [j.requestFile, this.binding.path, join25(this.binding.directory, "api-state.json")]) {
      const fd = openSync11(path, "r+");
      try {
        fsyncSync10(fd);
      } finally {
        closeSync11(fd);
      }
    }
    const now = this.clockNow();
    let reason = this.poisonReason;
    try {
      verifyPin(SELF7);
      verifyPin(PROOF_SOURCE2);
      verifyPin(this.options.prices);
      this.options.admission?.validateForwardSource();
    } catch {
      reason ??= "cash_owner_or_source_or_price_expired";
    }
    if (now.fault)
      reason ??= "cash_clock_fault";
    if (!Number.isFinite(Date.parse(start.startedAt)) || now.wall < Date.parse(start.startedAt))
      reason ??= "cash_start_clock_invalid";
    if (this.options.providerKind === "real-provider" && (!Number.isFinite(Date.parse(this.prices.observedAtUtc)) || now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc)))
      reason ??= "price_expired_or_clock_invalid";
    const r = this.options.providerKind === "local-mock" ? 0n : v.peakNano, t = this.count();
    if (t.known + t.pending + t.unknown + r > (this.options.admission?.envelopeNanoCny ?? 0n))
      reason ??= "cash_envelope_exhausted";
    const ticket = Object.freeze({ id: input.id, requestSeq: j.requestSeq, route: input.route, dispatchAllowed: !reason, peakReservationNanoCny: r.toString() });
    const state = { id: input.id, seq: j.requestSeq, route: input.route, start, reservation: reason ? 0n : r, phase: reason ? "denied" : "pending", amount: 0n, ticket };
    try {
      this.writer.append("start", { id: input.id, requestSeq: j.requestSeq, route: input.route, requestPin: input.capturedRequest, rawRequestSha256: j.requestSha256, startPrefix: input.journal.startPrefix, inputUpper: v.inputUpper, outputLimit: v.output, peakReservationNanoCny: r.toString(), reservedNanoCny: state.reservation.toString(), dispatchAllowed: !reason, reason: reason ?? null, hostWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString() });
    } catch (error) {
      this.poisonReason ??= "cash_admission_persistence_failed";
      throw error;
    }
    this.nextSeq++;
    this.states.set(j.requestSeq, state);
    this.ticketStates.set(ticket, state);
    if (reason)
      this.poisonReason ??= reason;
    return { admitted: !reason, ticket, ...reason ? { reason } : {} };
  }
  poison(reason) {
    demand(reason.length > 0 && reason.length <= 1024, "poison_reason");
    this.poisonReason ??= reason;
    if (!this.writer.fault())
      this.writer.append("poison", { reason });
    return this.snapshot();
  }
  finish(ticket, input) {
    try {
      return this.finishInternal(ticket, input);
    } catch (error) {
      this.poisonReason ??= "cash_finish_validation_failed";
      if (!this.writer.fault() && !this.closedPin)
        this.writer.append("poison", { reason: this.poisonReason, requestSeq: ticket.requestSeq });
      throw error;
    }
  }
  finishInternal(ticket, input) {
    demand(!this.closedPin, "cash_already_closed");
    const s = this.ticketStates.get(ticket);
    demand(s && s.seq === ticket.requestSeq && s.ticket === ticket, "cash_ticket_identity");
    const now = this.clockNow();
    let record, signature, source, unknown = false;
    if (input.kind === "journal-finish") {
      record = this.binding.finish(s.seq, input.journalRef);
      demand(record.requestSha256 === s.start.requestSha256 && record.requestFile === s.start.requestFile && record.route === s.route, "cash_finish_start_binding");
      signature = input.journalRef.finishLineSha256;
      source = { kind: "journal-finish", journalRef: input.journalRef };
    } else {
      demand(input.requestSeq === s.seq && input.evidence.files.length > 0, "failed_capture_binding");
      for (const p of input.evidence.files)
        verifyPin(p);
      this.binding.consume(input.evidence.originalPrefix);
      record = { ...s.start, ...input.evidence };
      signature = hash(JSON.stringify(input.evidence));
      source = { kind: "failed-capture", evidence: input.evidence };
      unknown = true;
      this.poisonReason ??= "source_journal_poisoned_capture";
    }
    if (s.finishSignature === signature)
      return this.snapshot();
    try {
      this.options.admission?.assertOwned();
    } catch {
      this.poisonReason ??= "cash_owner_lost";
    }
    let amount = s.reservation, observedUsage, estimate, responsePin, rawResponseSha;
    if (record.providerAttempted === false && record.confirmedNoForward === true && input.kind === "journal-finish")
      amount = 0n;
    else {
      if (!ticket.dispatchAllowed)
        this.poisonReason ??= "provider_forward_after_cash_denial";
      try {
        responsePin = input.kind === "journal-finish" && record.responseFile ? { path: record.responseFile, sha256: record.responseCompressedSha256 } : input.kind === "failed-capture" ? input.evidence.responsePin : undefined;
        rawResponseSha = input.kind === "journal-finish" ? record.responseSha256 : input.evidence.rawResponseSha256;
        demand(responsePin && rawResponseSha, "complete_response_missing");
        const raw = gzipProof(responsePin, rawResponseSha), data2 = JSON.parse(raw.toString("utf8"));
        observedUsage = data2.usage;
        demand(same(data2.usage, record.usage) && data2.model === record.servedModel || input.kind === "failed-capture" && same(data2.usage, input.evidence.usage), "response_usage_binding");
        const window = peakWindow(Date.parse(s.start.startedAt), now.wall), expired = now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc);
        const peak = window.peak || window.clockFault || now.fault || expired;
        estimate = this.options.providerKind === "local-mock" ? 0n : pricedUsage(observedUsage, true);
        amount = estimate;
        if (input.kind === "journal-finish" && (record.httpStatus !== 200 || record.fault || record.completionValid !== true)) {
          unknown = true;
          this.poisonReason ??= "provider_body_or_completion_not_complete";
        }
        if (window.clockFault || now.fault || expired) {
          unknown = true;
          this.poisonReason ??= "clock_or_price_unknown_at_capture";
        }
      } catch {
        unknown = true;
        this.poisonReason ??= "missing_or_invalid_complete_usage";
      }
    }
    if (input.kind === "failed-capture" && s.phase === "known" && responsePin && observedUsage && estimate === s.amount && rawResponseSha && rawResponseSha === s.lastResponseRawSha) {
      this.writer.append("late-evidence", { id: s.id, requestSeq: s.seq, source, responsePin, rawResponseSha256: rawResponseSha, observedUsage, amountNanoCny: s.amount.toString(), reason: "overlapping_known_finish_retained_once" });
      return this.snapshot();
    }
    if (input.kind === "failed-capture")
      unknown = true;
    if (s.phase === "unknown" || s.phase === "known" && s.finishSignature) {
      unknown = true;
      this.poisonReason ??= "conflicting_or_late_cash_finish";
    }
    if (unknown)
      amount = [s.reservation, s.amount, estimate ?? 0n].reduce((a, b) => a > b ? a : b);
    const phase = unknown ? "unknown" : "known";
    const data = { id: s.id, requestSeq: s.seq, phase, amountNanoCny: amount.toString(), peakReservationNanoCny: s.reservation.toString(), source, signature, responsePin: responsePin ?? null, rawResponseSha256: rawResponseSha ?? null, observedUsage: observedUsage ?? null, observedEstimatedNanoCny: estimate?.toString() ?? null, hostCaptureWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString(), clockFault: now.fault, poisonReason: this.poisonReason ?? null };
    try {
      this.writer.append("finish", data);
    } catch (error) {
      this.poisonReason ??= "cash_finish_persistence_failed";
      throw error;
    }
    s.phase = phase;
    s.amount = amount;
    s.finishSignature = signature;
    s.lastResponseRawSha = rawResponseSha;
    if (amount > s.reservation && record.providerAttempted !== false)
      this.poisonReason ??= "actual_estimate_exceeds_reservation";
    if (BigInt(this.snapshot().newExposureNanoCny) > (this.options.admission?.envelopeNanoCny ?? 0n))
      this.poisonReason ??= "actual_estimate_exceeds_envelope";
    return this.snapshot();
  }
  close() {
    if (this.closedPin)
      return this.closedPin;
    const inspection = inspectCampaignJournal2(this.options.journal.directory), snapshot = this.snapshot();
    const cashPrefix = this.writer.snapshot();
    let good = !this.writer.fault() && inspection.valid && inspection.accountingClosed && snapshot.pendingCount === 0 && snapshot.newUnknownCount === 0;
    try {
      this.options.admission?.assertOwned();
    } catch {
      good = false;
    }
    this.writer.close();
    const cashEvents = actualPin(this.writer.path);
    const value = { protocol: "cny-shadow-close-v2", runId: this.options.runId, ownerNonce: this.config.ownerNonce, configPin: this.configPin, cashEventsPin: cashEvents, cashPrefix, journalConfigPin: this.options.journal.configPin, journalSourcePin: this.options.journal.sourcePin, journalDirectory: resolve22(this.options.journal.directory), journalPrefix: inspection.prefix ?? this.binding.current(), journalValid: inspection.valid, journalAccountingClosed: inspection.accountingClosed, snapshot, releasePermitted: good, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
    const path = join25(this.directory, "cash-close.json"), fd = openSync11(path, "wx", 384);
    try {
      writeFileSync7(fd, JSON.stringify(value, null, 2) + `
`);
      fsyncSync10(fd);
    } finally {
      closeSync11(fd);
    }
    this.closedPin = actualPin(path);
    if (good)
      verifyCashClosure2(this.closedPin);
    return this.closedPin;
  }
}
function verifyCashClosure2(pin) {
  if (jsonPin(pin).protocol === "openrouter-usd-cash-close-v1")
    return verifyBenchmarkCashClosure2(pin);
  const proof = jsonPin(pin), config = jsonPin(proof.configPin);
  demand(proof.protocol === "cny-shadow-close-v2" && config.protocol === "cny-shadow-config-v2" && proof.runId === config.runId && proof.ownerNonce === config.ownerNonce, "cash_close_config");
  demand(config.providerKind === "real-provider" || config.providerKind === "local-mock", "cash_provider_kind");
  demand(config.pricingMode === "published-peak-conservative-upper-bound", "tb12_peak_upper_pricing_required");
  for (const p of config.cashSourcePins)
    verifyPin(p);
  const prices = validatePrices(config.pricesPin);
  verifyPin(proof.cashEventsPin);
  verifyPin(config.journalSourcePin);
  if (config.admissionPin) {
    const admission = jsonPin(config.admissionPin);
    demand(admission.protocol === "paid-resource-admission-v2" && admission.runId === config.runId && admission.owned.ownerNonce === config.ownerNonce && admission.selectedNewEnvelopeNanoCny === config.envelopeNanoCny && admission.carryNanoCny === config.carryNanoCny, "cash_admission_config_binding");
  }
  const binding = new JournalBinding(config.journalDirectory, config.journalConfigPin, config.journalSourcePin), raw = readFileSync14(proof.cashEventsPin.path);
  let at = 0, seq = 0, last = proof.configPin.sha256;
  const states = new Map;
  for (const lineText of raw.toString("utf8").split(`
`)) {
    if (!lineText)
      continue;
    const line = Buffer.from(lineText + `
`), e = JSON.parse(lineText);
    demand(Buffer.from(JSON.stringify(e) + `
`).equals(line) && e.protocol === "cny-shadow-event-v2" && e.eventSeq === seq && e.previousEventSha256 === last, "cash_event_chain");
    const d = e.data;
    if (e.kind === "start") {
      demand(!states.has(d.requestSeq) && d.requestSeq === states.size, "cash_start_sequence");
      const start = binding.start(d.requestSeq, d.startPrefix), body = gzipProof(d.requestPin, d.rawRequestSha256, undefined, 4 * 1024 ** 2), v = requestValues(body);
      demand(start.requestSha256 === d.rawRequestSha256 && start.requestCompressedSha256 === d.requestPin.sha256 && resolve22(start.requestFile) === resolve22(d.requestPin.path) && start.requestBytes === body.length && start.route === d.route && v.inputUpper === d.inputUpper && v.output === d.outputLimit, "cash_start_proof");
      const r = config.providerKind === "local-mock" ? 0n : v.peakNano;
      demand(typeof d.dispatchAllowed === "boolean" && r.toString() === d.peakReservationNanoCny && d.reservedNanoCny === (d.dispatchAllowed ? r : 0n).toString(), "cash_peak_reservation");
      states.set(d.requestSeq, { phase: d.dispatchAllowed ? "pending" : "denied", amount: 0n, reservation: BigInt(d.reservedNanoCny), start });
    } else if (e.kind === "finish") {
      const s = states.get(d.requestSeq);
      demand(s, "cash_finish_unknown");
      let min = 0n;
      if (d.source.kind === "journal-finish") {
        const receipt = binding.finish(d.requestSeq, d.source.journalRef);
        demand(d.signature === d.source.journalRef.finishLineSha256 && receipt.requestSha256 === s.start.requestSha256, "cash_finish_member");
        if (!(receipt.providerAttempted === false && receipt.confirmedNoForward === true)) {
          if (receipt.httpStatus !== 200 || receipt.fault || receipt.completionValid !== true)
            demand(d.phase === "unknown", "incomplete_provider_receipt_settled");
          demand(d.responsePin && d.rawResponseSha256 && resolve22(d.responsePin.path) === resolve22(receipt.responseFile) && d.responsePin.sha256 === receipt.responseCompressedSha256 && d.rawResponseSha256 === receipt.responseSha256, "cash_known_response_missing");
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand(same(data.usage, d.observedUsage) && same(data.usage, receipt.usage) && data.model === receipt.servedModel, "cash_usage_proof");
          const window = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs), expired = !Number.isFinite(Date.parse(prices.observedAtUtc)) || d.hostCaptureWallUnixMs - Date.parse(prices.observedAtUtc) > 24 * 3600000 || d.hostCaptureWallUnixMs < Date.parse(prices.observedAtUtc);
          if (window.clockFault || d.clockFault || expired)
            demand(d.phase === "unknown", "cash_clock_unknown_settled");
          try {
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, true);
          } catch {
            demand(d.phase === "unknown", "invalid_usage_settled");
            min = s.reservation;
          }
        }
      } else {
        demand(d.source.kind === "failed-capture" && d.phase === "unknown", "failed_capture_settled");
        for (const p of d.source.evidence.files)
          verifyPin(p);
        min = s.reservation;
        if (d.responsePin && d.rawResponseSha256) {
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand(same(data.usage, d.observedUsage), "late_usage_proof");
          try {
            const w = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs);
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, true);
          } catch {}
        }
      }
      if (s.phase === "unknown")
        demand(d.phase === "unknown", "sealed_unknown_reopened");
      if (d.phase === "unknown")
        min = [min, s.reservation, s.amount].reduce((a, b) => a > b ? a : b);
      demand((d.phase === "known" || d.phase === "unknown") && BigInt(d.amountNanoCny) >= min && (d.phase !== "known" || BigInt(d.amountNanoCny) === min), "cash_cost_replay");
      s.phase = d.phase;
      s.amount = BigInt(d.amountNanoCny);
      s.signature = d.signature;
      s.rawSha = d.rawResponseSha256;
    } else if (e.kind === "late-evidence") {
      const s = states.get(d.requestSeq);
      demand(s && s.phase === "known" && s.rawSha === d.rawResponseSha256 && d.source.kind === "failed-capture" && BigInt(d.amountNanoCny) === s.amount, "late_overlap_binding");
      for (const p of d.source.evidence.files)
        verifyPin(p);
      const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
      demand(same(data.usage, d.observedUsage), "late_overlap_usage");
    } else
      demand(e.kind === "poison", "cash_event_kind");
    at += line.length;
    seq++;
    last = hash(line);
  }
  demand(at === raw.length && same(proof.cashPrefix, { bytes: at, eventCount: seq, lastSha256: last }), "cash_exact_prefix");
  let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
  for (const s of states.values()) {
    if (s.phase === "known")
      known += s.amount;
    else if (s.phase === "unknown") {
      unknown += s.amount;
      unknownCount++;
    } else {
      pending += s.reservation;
      pendingCount++;
    }
  }
  const exposure = known + pending + unknown;
  demand(proof.snapshot.protocol === "cny-shadow-cash-v2" && proof.snapshot.runId === config.runId && proof.snapshot.currency === "CNY" && proof.snapshot.providerKind === config.providerKind && proof.snapshot.carriedOriginalUnknownNanoCny === config.carryNanoCny && proof.snapshot.newKnownEstimatedNanoCny === known.toString() && proof.snapshot.newPendingPeakNanoCny === pending.toString() && proof.snapshot.newUnknownPeakNanoCny === unknown.toString() && proof.snapshot.newExposureNanoCny === exposure.toString() && proof.snapshot.remainingNewEnvelopeNanoCny === (BigInt(config.envelopeNanoCny) - exposure).toString() && proof.snapshot.pendingCount === pendingCount && proof.snapshot.newUnknownCount === unknownCount && proof.snapshot.invoice === false && proof.snapshot.foreignExchangeConversion === false, "cash_snapshot_replay");
  const journal = inspectCampaignJournal2(config.journalDirectory);
  demand(journal.valid && journal.accountingClosed && journal.snapshot?.acceptedRequestCount === states.size && same(journal.prefix, proof.journalPrefix) && pendingCount === 0 && unknownCount === 0 && proof.releasePermitted === true, "cash_or_peer_not_closed");
  return { proof, config, states };
}

// scripts/terminal-bench-repair/tb12-v2/paid_admission.ts
var TB12_FAMILY = "terminal-bench-twelve-journal-v2";
var ROOT9 = resolve23(import.meta.dir, "../../..");
function durable3(path, value, replace = false) {
  mkdirSync9(dirname10(path), { recursive: true });
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`);
  const target = replace ? path + ".tmp-" + randomBytes3(8).toString("hex") : path;
  const fd = openSync12(target, "wx", 384);
  try {
    writeFileSync8(fd, raw);
    fsyncSync11(fd);
  } finally {
    closeSync12(fd);
  }
  demand(readFileSync15(target).equals(raw), "tb12_durable_readback");
  if (replace)
    renameSync3(target, path);
  demand(readFileSync15(path).equals(raw), "tb12_durable_commit_readback");
  return actualPin(path);
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/provider_gateway_v50.ts
import { randomBytes as randomBytes4, timingSafeEqual } from "crypto";
import { existsSync as existsSync9, readFileSync as readFileSync17, mkdirSync as mkdirSync10, writeFileSync as writeFileSync9 } from "fs";
import { join as join28 } from "path";
import { gzipSync as gzipSync5 } from "zlib";
init_campaign_contract();
init_paid_resource_proof_v2();

// scripts/benchmark-campaign/full-f/terminal-bench/benchmark-usd-cash.ts
import { closeSync as closeSync13, fsyncSync as fsyncSync12, openSync as openSync13, readFileSync as readFileSync16, readSync as readSync9, statSync as statSync10, writeSync as writeSync8 } from "fs";
import { join as join27, resolve as resolve24 } from "path";
init_cny_cash_shadow_v2();
init_paid_resource_proof_v2();
function cashForwardStateAllowed(closed, reason, policy = "stop") {
  return !closed && (!reason || policy === "record_and_continue" && ["usd_unknown_charge", "usd_failed_capture_unsettled"].includes(reason));
}
function durable4(path, value) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`), fd = openSync13(path, "wx", 384);
  try {
    let at = 0;
    while (at < raw.length) {
      const count3 = writeSync8(fd, raw, at, raw.length - at);
      demand(count3 > 0, "usd_cash_short_write");
      at += count3;
    }
    fsyncSync12(fd);
  } finally {
    closeSync13(fd);
  }
  demand(readFileSync16(path).equals(raw), "usd_cash_readback");
  return actualPin(path);
}
function validateUsdPrices3(pin, providerSlug = BENCHMARK_PROVIDER2.providerSlug) {
  const data = jsonPin(pin);
  demand(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER2.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand(same(data.reservationRates, BENCHMARK_PROVIDER2.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand(raw.data?.endpoints?.some((row) => row.provider_name === { relace: "Relace", digitalocean: "DigitalOcean", deepseek: "DeepSeek" }[providerSlug] && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER2.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart3(directory, data) {
  const raw = readFileSync16(join27(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand(hash(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route && same(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}
function createBenchmarkCash(options, provider) {
  if (!provider)
    return createCnyCashShadow(options);
  return new UsdCash3(options);
}

class UsdCash3 {
  options;
  states = new Map;
  tickets = new WeakSet;
  events = [];
  poisonReason;
  closed;
  fd;
  previousHash;
  capUsd;
  bytes = 0;
  directory;
  configPin;
  prices;
  config;
  constructor(options) {
    this.options = options;
    const admission = options.admission;
    demand(options.providerKind === "local-mock" || admission?.currency === "USD", "openrouter_usd_admission_required");
    this.directory = ordinaryDirectory(options.directory);
    this.prices = validateUsdPrices3(options.prices);
    const config = jsonPin(options.journal.configPin);
    demand(config.provider === "openrouter-deepseek" && config.currency === "USD" && config.campaign === options.runId && config.priorCampaignCostUpperBoundUsd === 0, "openrouter_cash_journal_binding");
    this.capUsd = admission?.capUsd ?? config.capUsd;
    demand(Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd, "openrouter_cash_cap_binding");
    this.config = {
      protocol: "openrouter-usd-cash-config-v1",
      runId: options.runId,
      currency: "USD",
      providerKind: options.providerKind,
      capUsd: this.capUsd,
      ownerNonce: admission?.owned.ownerNonce ?? null,
      scope: admission?.scope ?? "local-mock",
      unknownCostPolicy: options.unknownCostPolicy ?? "stop",
      admissionPin: admission?.proofPin ?? null,
      pricesPin: options.prices,
      journal: options.journal,
      sourcePin: actualPin(import.meta.path),
      createdAt: new Date().toISOString(),
      invoice: false,
      foreignExchangeConversion: false
    };
    this.configPin = durable4(join27(this.directory, "cash-config.json"), this.config);
    this.previousHash = this.configPin.sha256;
    this.fd = openSync13(join27(this.directory, "cash-events.jsonl"), "wx+", 384);
    fsyncSync12(this.fd);
    try {
      admission?.registerCash(this.configPin);
    } catch (error) {
      closeSync13(this.fd);
      throw error;
    }
  }
  append(kind, data) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + `
`);
    demand(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at = 0;
    while (at < raw.length) {
      const count3 = writeSync8(this.fd, raw, at, raw.length - at, this.bytes + at);
      demand(count3 > 0, "usd_cash_short_write");
      at += count3;
    }
    fsyncSync12(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand(readSync9(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw) && statSync10(join27(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash(raw);
    this.events.push(event);
  }
  snapshot() {
    let known = 0, pending = 0, unknown = 0, pendingCount = 0, unknownCount = 0;
    for (const state of this.states.values()) {
      if (state.phase === "known")
        known += state.amount;
      if (state.phase === "pending") {
        pending += state.ticket.reservationUsd;
        pendingCount++;
      }
      if (state.phase === "unknown") {
        unknown += state.amount;
        unknownCount++;
      }
    }
    return {
      protocol: "openrouter-usd-cash-state-v1",
      currency: "USD",
      runId: this.options.runId,
      capUsd: this.capUsd,
      billedUsd: known,
      pendingReservationUsd: pending,
      unknownReservationUsd: unknown,
      exposureUpperBoundUsd: known + pending + unknown,
      remainingUsd: this.capUsd - known - pending - unknown,
      pendingCount,
      newUnknownCount: unknownCount,
      poisoned: !!this.poisonReason,
      poisonReason: this.poisonReason ?? null,
      invoice: false,
      foreignExchangeConversion: false
    };
  }
  poison(reason) {
    this.poisonReason ??= reason;
  }
  beforeForward(input) {
    demand(cashForwardStateAllowed(this.closed, this.poisonReason, this.options.unknownCostPolicy), "usd_cash_closed_or_poisoned");
    const admission = this.options.admission;
    admission?.validateForwardSource();
    verifyPin(this.options.prices);
    verifyPin(this.config.sourcePin);
    verifyPin(this.options.journal.sourcePin);
    const observed = Date.parse(this.prices.observedAtUtc);
    if (this.options.providerKind === "real-provider")
      demand(Number.isFinite(observed) && Date.now() >= observed && Date.now() - observed <= 86400000, "openrouter_price_expired");
    const j = input.journal.admitted, raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2);
    const inspected = inspectCampaignJournal(this.options.journal.directory);
    demand(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve24(input.capturedRequest.path) === resolve24(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
    const reservationUsd = this.options.providerKind === "local-mock" ? 0 : j.reservationUsd;
    const permitted = this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 0.000000001;
    const ticket = Object.freeze({
      requestSeq: j.requestSeq,
      route: input.route,
      reservationUsd,
      currency: "USD",
      dispatchAllowed: permitted
    });
    const start = { ticket, requestPin: input.capturedRequest, requestSha256: j.requestSha256, startPrefix: input.journal.startPrefix };
    demand(boundStart3(this.options.journal.directory, start).reservationUsd === j.reservationUsd, "usd_actual_reservation_binding");
    this.append("start", start);
    this.states.set(j.requestSeq, { ticket, phase: permitted ? "pending" : "denied", amount: 0 });
    this.tickets.add(ticket);
    if (!permitted)
      this.poison("usd_envelope_exhausted");
    return { admitted: permitted, ticket, ...!permitted ? { reason: "usd_envelope_exhausted" } : {} };
  }
  finish(given, finish) {
    demand(!this.closed && this.tickets.has(given), "usd_ticket_not_owned");
    const ticket = given, state = this.states.get(ticket.requestSeq);
    const signature = hash(JSON.stringify(finish));
    if (state.signature) {
      demand(state.signature === signature, "usd_duplicate_finish_changed");
      return this.snapshot();
    }
    let phase, amount, receipt;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync16(join27(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand(hash(line) === ref.finishLineSha256, "usd_finish_line_changed");
      const event = JSON.parse(line.toString("utf8"));
      receipt = event.record;
      demand(event.kind === "finish" && event.requestSeq === ticket.requestSeq && receipt.route === ticket.route && inspectCampaignJournal(this.options.journal.directory).valid, "usd_finish_journal_binding");
      phase = receipt.costBasis === "reservation" ? "unknown" : "known";
      amount = this.options.providerKind === "local-mock" ? 0 : receipt.usdUpperBound;
    } else {
      phase = "unknown";
      amount = ticket.reservationUsd;
      this.poison("usd_failed_capture_unsettled");
    }
    demand(Number.isFinite(amount) && amount >= 0, "usd_finish_amount_invalid");
    this.append("finish", {
      ticket,
      signature,
      phase,
      amountUsd: amount,
      finish,
      costBasis: receipt?.costBasis ?? "reservation",
      generationId: receipt?.requestId ?? null,
      providerName: receipt?.providerName ?? null,
      servedModel: receipt?.servedModel ?? null
    });
    state.phase = phase;
    state.amount = amount;
    state.signature = signature;
    if (phase === "unknown")
      this.poison("usd_unknown_charge");
    if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 0.000000001)
      this.poison("usd_cost_exceeded_cap");
    return this.snapshot();
  }
  close() {
    if (this.closed)
      return this.closed;
    fsyncSync12(this.fd);
    closeSync13(this.fd);
    const inspection = inspectCampaignJournal(this.options.journal.directory), state = this.snapshot();
    this.closed = durable4(join27(this.directory, "cash-close.json"), {
      protocol: "openrouter-usd-cash-close-v1",
      currency: "USD",
      configPin: this.configPin,
      cashEventsPin: actualPin(join27(this.directory, "cash-events.jsonl")),
      snapshot: state,
      journalDirectory: this.options.journal.directory,
      journalPrefix: inspection.prefix,
      releasePermitted: inspection.valid && inspection.accountingClosed && state.pendingCount === 0 && state.newUnknownCount === 0,
      scoreCertificate: false,
      invoice: false,
      foreignExchangeConversion: false
    });
    return this.closed;
  }
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/owner_forward_gate.ts
async function forwardAfterOwnerGuard(options) {
  options.validateForwardSource();
  await options.ownerForwardGuard();
  if (!options.transport)
    throw Error("terminal_full_F_shared_transport_required");
  options.markAttempted();
  return options.transport(options.wire);
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/provider_gateway_v50.ts
function providerGateway(options) {
  demand(options.kind === "local-mock" || options.admission && options.providerKey, "tb12_provider_admission_required");
  const token = randomBytes4(32).toString("hex"), directory = join28(options.output, "provider");
  mkdirSync10(directory, { recursive: true });
  const journal = createCampaignJournal({
    directory,
    campaign: options.runId,
    capUsd: options.provider ? options.admission?.capUsd ?? 100 : 100,
    priorCampaignCostUpperBoundUsd: 0,
    outputDirectory: directory,
    provider: options.provider
  });
  const journalSource = actualPin("F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/benchmark-campaign/full-f/shared/digitalocean-journal.ts");
  const cashOptions = {
    directory: join28(options.output, "cash"),
    runId: options.runId,
    providerKind: options.kind,
    admission: options.admission,
    prices: options.prices,
    journal: { directory, configPin: actualPin(join28(directory, "journal-config.json")), sourcePin: journalSource },
    unknownCostPolicy: "record_and_continue"
  };
  const cash = options.provider ? createBenchmarkCash(cashOptions, options.provider) : createCnyCashShadow2(cashOptions);
  const plans = new Map, calls = [], pending = new Map;
  let fatal, stopped = false;
  const equal = (value) => {
    const a = Buffer.from(value), b = Buffer.from(token);
    return a.length === b.length && timingSafeEqual(a, b);
  };
  const persist = () => durable3(join28(options.output, "provider-route-receipts.json"), {
    protocol: "tb12-provider-route-receipts-v1",
    family: TB12_FAMILY,
    runId: options.runId,
    providerKind: options.kind,
    calls,
    pending: Object.fromEntries(pending),
    fatal: fatal ?? null,
    modelCalls: options.kind === "real-provider" ? calls.filter((call) => call.providerAttempted).length : 0,
    cashSnapshot: cash.snapshot(),
    journalSnapshot: journal.snapshot(),
    legacyUsdFieldsUsePublishedPeakUpperBound: true,
    realApiCredentialNotGivenToEngine: true,
    authenticationTokenExcluded: true
  }, true);
  const finishTicket = (ticket, input) => {
    const before = journal.snapshot().durablePrefix.bytes;
    const result = journal.finish(input), after = journal.snapshot().durablePrefix;
    cash.finish(ticket, { kind: "journal-finish", journalRef: {
      finishOffset: before,
      finishEnd: after.bytes,
      finishLineSha256: after.lastSha256
    } });
    return result;
  };
  const server = Bun.serve({
    idleTimeout: 0,
    hostname: "127.0.0.1",
    port: 0,
    maxRequestBodySize: 4 * 1024 ** 2,
    async fetch(request) {
      if (!equal(request.headers.get("authorization")?.replace(/^Bearer /, "") ?? ""))
        return Response.json({ error: { message: "Unauthorized TB12 provider gateway" } }, { status: 401 });
      const path = new URL(request.url).pathname;
      if (request.method !== "POST" || !path.endsWith("/v1/chat/completions"))
        return Response.json({ error: { message: "Unsupported route" } }, { status: 404 });
      const route = path.slice(1, -"/v1/chat/completions".length), plan = plans.get(route);
      if (!plan)
        return Response.json({ error: { message: "Unknown owned attempt" } }, { status: 422 });
      if (stopped || plan.sealed || fatal)
        return Response.json({ error: { message: "Owned provider admission closed" } }, { status: 409 });
      let attempted = false, ticket, admitted, row, rawResponse, httpStatus;
      try {
        const coreRaw = await request.text();
        let body = JSON.parse(coreRaw);
        demand(body.model === (options.provider?.model ?? "deepseek-flash") && Array.isArray(body.messages) && body.stream !== true, "tb12_provider_profile");
        options.sourceGuard();
        body = benchmarkProviderRequest2(body, options.inference ?? BENCHMARK_INFERENCE2, options.provider);
        if (plan.board) {
          verifyPin(plan.board);
          const image = readFileSync17(plan.board.path);
          const user = body.messages.find((message) => message.role === "user");
          demand(user && typeof user.content === "string", "tb12_initial_public_image_message");
          user.content = [{ type: "text", text: user.content }, { type: "image_url", image_url: { url: "data:image/png;base64," + image.toString("base64") } }];
        }
        const wire = JSON.stringify(body);
        demand(!options.providerKey || !wire.includes(options.providerKey), "tb12_credential_in_request_body");
        admitted = journal.admit({ route, rawRequest: wire });
        if (!admitted.admitted)
          return Response.json({ error: { message: admitted.reason } }, { status: 409 });
        const seq = admitted.requestSeq, corePath = join28(directory, "core-" + seq + "-request.json.gz");
        writeFileSync9(corePath, gzipSync5(coreRaw), { flag: "wx" });
        const state = jsonPin(actualPin(join28(directory, "api-state.json")));
        const cashAdmission = cash.beforeForward({
          id: options.runId + "/" + seq,
          route,
          rawRequest: Buffer.from(wire),
          journal: { admitted, startPrefix: state.durablePrefix },
          capturedRequest: actualPin(admitted.requestFile)
        });
        ticket = cashAdmission.ticket;
        row = {
          index: seq,
          route,
          taskId: plan.taskId,
          arm: plan.arm,
          requestSha256: hash(wire),
          coreRequestPin: actualPin(corePath),
          providerRequestPin: actualPin(admitted.requestFile),
          startedAt: new Date().toISOString(),
          wireParameters: {
            model: body.model,
            temperature: body.temperature,
            seed: body.seed,
            reasoning_effort: body.reasoning_effort,
            thinking: body.thinking,
            max_tokens: body.max_tokens,
            tool_choice: body.tool_choice ?? null
          },
          publicImagePin: plan.board ?? null,
          providerAttempted: false
        };
        calls.push(row);
        pending.set(route, (pending.get(route) ?? 0) + 1);
        persist();
        if (!cashAdmission.admitted) {
          finishTicket(ticket, { requestSeq: seq, providerAttempted: false, confirmedNoForward: true, fault: cashAdmission.reason });
          return Response.json({ error: { message: cashAdmission.reason } }, { status: 409 });
        }
        if (options.kind === "local-mock") {
          const steps = [
            { name: "bash", args: { command: "printf 'before\\n' > /app/objrun-tb12-mock.txt", timeout_ms: 1e4 } },
            { name: "read", args: { file_path: "/app/objrun-tb12-mock.txt" } },
            { name: "write", args: { file_path: "/app/objrun-tb12-mock.txt", content: `written
` } },
            { name: "edit", args: { file_path: "/app/objrun-tb12-mock.txt", old_string: "written", new_string: "edited" } },
            { name: "glob", args: { pattern: "objrun-tb12-mock.txt", path: "/app" } },
            { name: "grep", args: { pattern: "edited", path: "/app/objrun-tb12-mock.txt" } },
            ...plan.arm === "F" ? [{ name: "verify", args: { answer: "tb12-mock-final" } }] : [],
            { name: "submit", args: { answer: "tb12-mock-final" } },
            ...plan.arm === "F" ? [
              { name: "write", args: { file_path: "/app/objrun-tb12-mock.txt", content: `repaired-after-failed-submit
` } },
              { name: "verify", args: { answer: "tb12-mock-repaired" } },
              { name: "submit", args: { answer: "tb12-mock-repaired" } }
            ] : []
          ];
          const action = body.tool_choice?.function?.name === "submit" ? { name: "submit", args: { answer: "tb12-mock-final" } } : steps[Math.min(plan.steps++, steps.length - 1)];
          demand(body.tools?.some((tool) => tool.function?.name === action.name), "tb12_mock_tool_unavailable");
          httpStatus = 200;
          rawResponse = JSON.stringify({
            id: "tb12-local-mock-" + route.replaceAll("/", "-") + "-" + seq,
            model: options.provider?.model ?? "deepseek-flash",
            provider: options.provider ? "DeepSeek" : undefined,
            choices: [{ index: 0, finish_reason: "tool_calls", message: { role: "assistant", content: null, tool_calls: [{
              id: "tb12-mock-tool-" + seq,
              type: "function",
              function: { name: action.name, arguments: JSON.stringify(action.args) }
            }] } }],
            usage: { cost: 0, prompt_tokens: 0, completion_tokens: 0, prompt_cache_hit_tokens: 0, prompt_cache_miss_tokens: 0 }
          });
          attempted = true;
          row.providerAttempted = false;
          row.mockTransportAttempted = true;
        } else {
          demand(options.ownerForwardGuard, "pipeline_actual_before_forward_guard_required");
          const captured = await forwardAfterOwnerGuard({ validateForwardSource: () => options.admission.validateForwardSource(), ownerForwardGuard: options.ownerForwardGuard, markAttempted: () => {
            attempted = true;
            row.providerAttempted = true;
          }, transport: options.transport, wire });
          httpStatus = captured.httpStatus;
          rawResponse = captured.rawResponse;
          demand(Buffer.byteLength(rawResponse) <= 2 * 1024 ** 2, "terminal_full_F_provider_response_limit");
        }
        const finished = finishTicket(ticket, { requestSeq: seq, providerAttempted: attempted, httpStatus, rawResponse });
        Object.assign(row, finished.receipt);
        row.responseSha256 = hash(rawResponse);
        row.usage = finished.receipt.usage;
        row.servedModel = finished.receipt.servedModel;
        row.requestId = finished.receipt.requestId;
        row.httpStatus = httpStatus;
        row.finishedAt = finished.receipt.finishedAt;
        if (!isNonGenerationRateRejection(finished.receipt) && (finished.receipt.fault || finished.receipt.completionValid !== true))
          fatal ??= "provider_receipt_or_completion_fault";
        return new Response(rawResponse, { status: httpStatus, headers: { "content-type": "application/json" } });
      } catch (error) {
        fatal ??= error instanceof Error ? error.message : "ProviderGatewayFault";
        if (row)
          row.fault = fatal;
        if (rawResponse !== undefined && row) {
          const path2 = join28(directory, "failed-" + row.index + "-response.json.gz");
          if (!existsSync9(path2))
            writeFileSync9(path2, gzipSync5(rawResponse), { flag: "wx" });
          row.failedResponsePin = actualPin(path2);
        }
        if (admitted?.admitted)
          try {
            finishTicket(ticket, {
              requestSeq: admitted.requestSeq,
              providerAttempted: attempted,
              httpStatus,
              rawResponse,
              confirmedNoForward: attempted ? undefined : true,
              fault: fatal
            });
          } catch {}
        return Response.json({ error: { message: "Owned provider evidence fault" } }, { status: 503 });
      } finally {
        if (row) {
          row.providerAttempted = options.kind === "real-provider" && attempted;
          pending.set(route, Math.max(0, (pending.get(route) ?? 1) - 1));
        }
        try {
          persist();
        } catch {
          fatal ??= "provider_route_capture_fault";
        }
      }
    }
  });
  persist();
  return {
    origin: "http://127.0.0.1:" + server.port,
    token,
    journal,
    cash,
    calls,
    pending,
    register(route, taskId, arm, board) {
      demand(arm === "F", "terminal_full_F_no_U");
      demand(!plans.has(route), "tb12_duplicate_route");
      plans.set(route, { taskId, arm, sealed: false, steps: 0, board });
    },
    seal(route) {
      const plan = plans.get(route);
      demand(plan, "tb12_unknown_route");
      plan.sealed = true;
    },
    fault() {
      return fatal;
    },
    async stop() {
      stopped = true;
      for (const plan of plans.values())
        plan.sealed = true;
      const expiry = Date.now() + 330000;
      while ([...pending.values()].some((value) => value !== 0) && Date.now() < expiry)
        await Bun.sleep(100);
      demand([...pending.values()].every((value) => value === 0), "tb12_provider_transfers_still_pending");
      await server.stop(true);
      persist();
      durable3(join28(options.output, "provider-native-close.json"), {
        protocol: "tb12-provider-native-close-v1",
        runId: options.runId,
        port: server.port,
        serverClosed: true,
        pendingCount: 0,
        closedAtUtc: new Date().toISOString(),
        tokenExcluded: true
      });
    },
    close() {
      const exported = journal.exportLegacyLedger(), cashClose = cash.close();
      journal.close();
      persist();
      return { exported, cashClose };
    }
  };
}

// scripts/benchmark-campaign/full-f/terminal-bench/freeze_engine.ts
init_paid_resource_proof_v2();
import { readFileSync as readFileSync18, mkdirSync as mkdirSync12, writeFileSync as writeFileSync11 } from "fs";
import { join as join30, resolve as resolve26 } from "path";

// scripts/benchmark-campaign/full-f/terminal-bench/pending-interfaces/required_fault_transform.ts
function requiredFaultSource(source) {
  const marker = `const why = msg(e);
      const serviceError =`;
  if (source.split(marker).length !== 2)
    throw Error("required_fault_kernel_shape");
  const cleanup = `const why = msg(e);
      if (e instanceof Error && e.name === "RequiredToolCallMissing") {
        const verdict=JSON.stringify({pass:0,valid:false,outcome:"submission_protocol_error",why});
        run(this.#store.rw,"update task set state='failed',result=? where id=? and state not in ('done','failed')",[verdict,p.task]);
        run(this.#store.rw,\`update "\${p.sub}" set done=1,status='dead_failed' where task=? and done=0\`,[p.task]);
        run(this.#store.rw,\`update "\${tableNameOf("agent_{}_ctx",p.agent)}" set done=1 where instance=?\`,[p.instance]);
        deliver(this.#store.rw,{agent:p.agent,instance:p.instance,unit:p.unit,by:"kernel",body:JSON.stringify({stuck:why,protocolFault:"RequiredToolCallMissing",responseSynthesized:false})});
        this.#answerAll(p.task,p.sub);
        this.#log.error(\`\${p.task} stopped after mandatory-tool retries were exhausted: \${why}\`);
        this.wake();return;
      }
      const serviceError =`;
  return source.replace(marker, cleanup);
}

// scripts/benchmark-campaign/full-f/terminal-bench/pending-interfaces/grader_transport_transform.ts
function graderTransportSource(source) {
  const replace = (before, after) => {
    if (source.split(before).length !== 2)
      throw Error("grader_transport_source_shape:" + before);
    source = source.replace(before, after);
  };
  replace("function remote(url: string): Handle {", "function remote(url: string, timeoutMs = 120000): Handle {");
  replace("call: remote(r.name) }", "call: remote(r.name, r.expect_ms) }");
  replace("body: JSON.stringify(arg ?? {}),", `body: JSON.stringify(arg ?? {}),
      signal: AbortSignal.timeout(timeoutMs),`);
  replace('...(trusted ? { redirect: "error" } : {})', '...(trusted ? { redirect: "error", timeout: false } : {})');
  return source;
}

// scripts/terminal-bench-repair/tb12-v2/host_engine.ts
init_paid_resource_proof_v2();
import { randomBytes as randomBytes5 } from "crypto";
import { spawn } from "child_process";
import { existsSync as existsSync10, mkdirSync as mkdirSync11, writeFileSync as writeFileSync10 } from "fs";
import { dirname as dirname11, join as join29, resolve as resolve25 } from "path";
init_benchmark_inference();
var ROOT10 = resolve25(import.meta.dir, "../../..");
async function startEngine(options) {
  verifyPin(options.bundle);
  demand(!existsSync10(join29(dirname11(process.execPath), "config.yaml")), "tb12_bun_neighbor_config");
  const probe = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("") });
  const port = probe.port;
  await probe.stop(true);
  const apiToken = randomBytes5(32).toString("hex"), publisherToken = randomBytes5(32).toString("hex");
  options.onSecret?.(apiToken);
  options.onSecret?.(publisherToken);
  mkdirSync11(options.directory, { recursive: true });
  const config = join29(options.directory, "config.yaml");
  const settings = {
    server: { host: "127.0.0.1", port, bodyLimit: 1048576, shutdownTimeout: 2000 },
    log: { level: "warn" },
    db: {
      file: "./data/h2h.sqlite",
      sealed: "./data/sealed.sqlite",
      pragmas: { journal_mode: "WAL", synchronous: "FULL", foreign_keys: "ON", busy_timeout: 5000 }
    },
    api: { prefix: "/api", token: apiToken, publisherToken, allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 },
    llm: { ...BENCHMARK_INFERENCE },
    cors: { enabled: false, origin: "*" }
  };
  writeFileSync10(config, JSON.stringify(settings), { flag: "wx", mode: 384 });
  durable3(join29(options.directory, "config-public.json"), {
    ...settings,
    api: { ...settings.api, token: "REDACTED", publisherToken: "REDACTED" },
    originalConfigSha256: hash(JSON.stringify(settings)),
    originalConfigPrivate: true
  });
  const environment = {};
  for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "COMSPEC"])
    if (process.env[name])
      environment[name] = process.env[name];
  Object.assign(environment, {
    TGENGIN_CONFIG: config,
    TGENGIN_PUBLISHER_TOKEN: publisherToken,
    DEEPSEEK_API_KEY: options.proxyKey,
    OPENROUTER_API_KEY: options.proxyKey,
    TGENGIN_GRADER_TOKEN: options.graderToken,
    TGENGIN_GRADER_ORIGINS: options.graderOrigins.join(",")
  });
  const startedAt = new Date().toISOString(), startedMono = performance.now();
  const child = spawn(process.execPath, [options.bundle.path], {
    env: environment,
    windowsHide: true,
    cwd: options.directory,
    stdio: ["ignore", "pipe", "pipe"]
  });
  demand(child.pid !== undefined, "tb12_engine_pid_missing");
  const chunks = [[], []], bytes = [0, 0], captureFaults = [];
  let exitObserved = false, closeObserved = false, exitCode = null, signal = null;
  for (const [index, stream] of [child.stdout, child.stderr].entries())
    stream?.on("data", (chunk) => {
      bytes[index] += chunk.length;
      if (bytes[index] > 2 * 1024 ** 2) {
        captureFaults.push("host-engine-stream-limit");
        child.kill("SIGKILL");
        return;
      }
      chunks[index].push(Buffer.from(chunk));
    });
  child.on("exit", (code, why) => {
    exitObserved = true;
    exitCode = code;
    signal = why;
  });
  const closed = new Promise((resolveClose) => child.on("close", () => {
    closeObserved = true;
    resolveClose();
  }));
  child.on("error", (error) => captureFaults.push(error.name));
  const base2 = "http://127.0.0.1:" + port + "/api";
  const stop = async () => {
    if (!closeObserved) {
      child.kill("SIGTERM");
      await Promise.race([closed, Bun.sleep(5000)]);
      if (!closeObserved) {
        child.kill("SIGKILL");
        await Promise.race([closed, Bun.sleep(5000)]);
      }
    }
    demand(exitObserved && closeObserved, "tb12_engine_actual_exit_and_close_required");
    const stdout = join29(options.directory, "engine.stdout"), stderr = join29(options.directory, "engine.stderr");
    writeFileSync10(stdout, Buffer.concat(chunks[0]), { flag: "wx" });
    writeFileSync10(stderr, Buffer.concat(chunks[1]), { flag: "wx" });
    const receipt = durable3(join29(options.directory, "engine-close.json"), {
      protocol: "tb12-host-engine-exact-close-v1",
      pid: child.pid,
      argv: [process.execPath, options.bundle.path],
      startedAtUtc: startedAt,
      closedAtUtc: new Date().toISOString(),
      monotonicSeconds: (performance.now() - startedMono) / 1000,
      exitObserved,
      closeObserved,
      exitCode,
      signal,
      port,
      captureFaults,
      bundle: options.bundle,
      stdout: actualPin(stdout),
      stderr: actualPin(stderr),
      projectApiCredentialInChild: false
    });
    return receipt;
  };
  let healthy = false;
  for (let step = 0;step < 200; step++) {
    if (closeObserved)
      break;
    try {
      const response = await fetch(base2 + "/health", { signal: AbortSignal.timeout(1000) });
      if (response.ok) {
        const data = await response.json();
        demand(data.db.replaceAll("\\", "/").toLowerCase() === join29(options.directory, "data/h2h.sqlite").replaceAll("\\", "/").toLowerCase(), "tb12_engine_wrong_database");
        healthy = true;
        break;
      }
    } catch (error) {
      if (error instanceof Error && error.message === "tb12_engine_wrong_database") {
        await stop();
        throw error;
      }
    }
    await Bun.sleep(100);
  }
  if (!healthy) {
    await stop();
    throw Error("tb12_frozen_engine_startup_failed");
  }
  const unauth = await fetch(base2 + "/exec", { method: "POST", headers: { "content-type": "application/json" }, body: '{"sql":"select 1"}' });
  if (unauth.status !== 401) {
    await stop();
    throw Error("tb12_engine_unauthenticated");
  }
  return {
    pid: child.pid,
    port,
    base: base2,
    directory: options.directory,
    stop,
    async api(method, path, body) {
      const response = await fetch(base2 + path, {
        method,
        headers: {
          authorization: "Bearer " + apiToken,
          "X-TGEngin-Publisher": publisherToken,
          ...body === undefined ? {} : { "content-type": "application/json" }
        },
        ...body === undefined ? {} : { body: JSON.stringify(body) },
        signal: AbortSignal.timeout(120000)
      });
      const value = await response.json();
      if (!response.ok)
        throw Error("Owned engine API " + response.status + " " + path + " " + JSON.stringify(value));
      return value;
    }
  };
}

// scripts/benchmark-campaign/full-f/terminal-bench/freeze_engine.ts
var root2 = resolve26(import.meta.dir, "../../../..");
function submissionRetrySource(source) {
  const target = "return await generateText({";
  demand(source.split(target).length === 2, "submission_transform_generateText_shape");
  source = source.replace(target, "const submittedResult = await generateText({");
  const boundary = `abortSignal: wall.signal,
              });`;
  demand(source.split(boundary).length === 2, "submission_transform_boundary_shape");
  source = source.replace(boundary, boundary + `
              if (officialOpenRouter && u.mustCall && submittedResult.finishReason !== "length" &&
                  (submittedResult.toolCalls.length !== 1 || submittedResult.toolCalls[0]?.toolName !== u.mustCall)) {
                const missing = new Error("The required " + u.mustCall + " tool was not called exactly once");
                missing.name = "RequiredToolCallMissing";
                throw missing;
              }
              return submittedResult;`);
  const retry = "if (!listed(e, retryOn)) throw e;";
  demand(source.split(retry).length === 2, "submission_transform_retry_shape");
  return source.replace(retry, 'if (!(e instanceof Error && e.name === "RequiredToolCallMissing") && !listed(e, retryOn)) throw e;');
}
async function freezeEngine(directory) {
  mkdirSync12(directory, { recursive: true });
  const original = join30(root2, "app/src/llm/index.ts");
  const transformed = submissionRetrySource(readFileSync18(original, "utf8"));
  const source = join30(directory, "bench-llm-transformed.ts");
  writeFileSync11(source, transformed, { flag: "wx" });
  const kernelOriginal = join30(root2, "app/src/engine/loop.ts");
  const kernelTransformed = requiredFaultSource(readFileSync18(kernelOriginal, "utf8"));
  const kernelSource = join30(directory, "bench-kernel-transformed.ts");
  writeFileSync11(kernelSource, kernelTransformed, { flag: "wx" });
  const registryOriginal = join30(root2, "app/src/engine/registry.ts");
  const registryTransformed = graderTransportSource(readFileSync18(registryOriginal, "utf8"));
  const registrySource = join30(directory, "bench-grader-registry-transformed.ts");
  writeFileSync11(registrySource, registryTransformed, { flag: "wx" });
  const result = await Bun.build({
    entrypoints: [join30(root2, "app/src/main.ts")],
    outdir: directory,
    target: "bun",
    minify: false,
    sourcemap: "external",
    plugins: [{ name: "tb-required-submit-retry", setup(build) {
      build.onLoad({ filter: /[\\/]app[\\/]src[\\/]llm[\\/]index\.ts$/ }, () => ({ contents: transformed, loader: "ts" }));
      build.onLoad({ filter: /[\\/]app[\\/]src[\\/]engine[\\/]loop\.ts$/ }, () => ({ contents: kernelTransformed, loader: "ts" }));
      build.onLoad({ filter: /[\\/]app[\\/]src[\\/]engine[\\/]registry\.ts$/ }, () => ({ contents: registryTransformed, loader: "ts" }));
    } }]
  });
  demand(result.success, "tb12_project_engine_bundle_failed");
  const files = result.outputs.map((output) => actualPin(output.path));
  const executable = files.find((pin) => pin.path.endsWith("main.js"));
  demand(executable, "tb12_project_engine_bundle_missing");
  const proof = {
    protocol: "tb-required-submit-existing-retry-build-v1",
    original: actualPin(original),
    transformed: actualPin(source),
    transform: actualPin(import.meta.path),
    retryTimesUnchanged: 3,
    maxTokensUnchanged: 16384,
    reasoningUnchanged: "high",
    originalDeadlineUnchanged: true,
    responseSynthesis: false,
    files,
    executable
  };
  Object.assign(proof, {
    kernelOriginal: actualPin(kernelOriginal),
    kernelTransformed: actualPin(kernelSource),
    kernelTransform: actualPin(join30(import.meta.dir, "pending-interfaces/required_fault_transform.ts")),
    exhaustedMandatoryResponse: "invalid-native-closed",
    taskScoreSynthesized: false
  });
  Object.assign(proof, {
    graderRegistryOriginal: actualPin(registryOriginal),
    graderRegistryTransformed: actualPin(registrySource),
    graderRegistryTransform: actualPin(join30(import.meta.dir, "pending-interfaces/grader_transport_transform.ts")),
    authenticatedGraderSocketIdleLimitDisabled: true,
    declaredGraderWholeRequestDeadlinePreserved: true
  });
  writeFileSync11(join30(directory, "submission-build-proof.json"), JSON.stringify(proof, null, 2) + `
`, { flag: "wx" });
  return { ...proof, hostBun: actualPin(process.execPath), hostBunVersion: Bun.version, originalEntry: actualPin(join30(root2, "app/src/main.ts")) };
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/http_transport_v5/fetch.ts
function infrastructureHttpFetch(url, init, wallTimeoutMs) {
  if (!Number.isFinite(wallTimeoutMs) || wallTimeoutMs <= 0)
    throw Error("original_wall_deadline_required");
  return fetch(url, { ...init, signal: AbortSignal.timeout(wallTimeoutMs), ...{ timeout: false } });
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/stand_process.ts
init_paid_resource_proof_v2();
import { spawn as spawn2 } from "child_process";
import { existsSync as existsSync11, mkdirSync as mkdirSync13, writeFileSync as writeFileSync12 } from "fs";
import { join as join31 } from "path";
async function startStand(options) {
  mkdirSync13(options.output, { recursive: true });
  const python = "D:/ProgramData/anaconda3/python.exe";
  const args = ["-B", "-X", "utf8", options.script, "--base-proof", options.baseProof, "--output", join31(options.output, "stand")];
  const environment = {};
  for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "COMSPEC"])
    if (process.env[name])
      environment[name] = process.env[name];
  environment.OBJRUN_TB12_STAND_TOKEN = options.token;
  for (const key of ["NOVAEVE_RESOURCE_PARENT_PID", "NOVAEVE_RESOURCE_LEASE_PID", "NOVAEVE_RESOURCE_MEMORY_MB", "NOVAEVE_RESOURCE_GROWTH_BYTES", "NOVAEVE_RESOURCE_BENCH", "NOVAEVE_RESOURCE_TOKEN", "NOVAEVE_ROOT_ONLY_DISPATCH"]) {
    demand(process.env[key], "pipeline_actual_resource_env_required:" + key);
    environment[key] = process.env[key];
  }
  environment.NOVAEVE_ACTIVATION_PATH = "F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\novaeve-formal-20261013\\activation-adopted-v48.json";
  environment.NOVAEVE_BROKER_CONTROL_PATH = "F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\novaeve-formal-20261013\\broker\\control-adopted-v48.private.json";
  environment.DOCKER_HOST = "tcp://127.0.0.1:18750";
  const child = spawn2(python, args, { env: environment, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  demand(child.pid !== undefined, "tb12_stand_native_pid_required");
  const start = new Date().toISOString(), chunks = [[], []], bytes = [0, 0], faults = [];
  let carry = "", ready, exitObserved = false, closeObserved = false, exitCode = null, signal = null;
  for (const [index, stream] of [child.stdout, child.stderr].entries())
    stream?.on("data", (chunk) => {
      bytes[index] += chunk.length;
      if (bytes[index] > 2 * 1024 ** 2) {
        faults.push("stand-stream-bound");
        child.kill("SIGKILL");
        return;
      }
      chunks[index].push(Buffer.from(chunk));
      if (index === 0 && !ready) {
        carry += chunk.toString("utf8");
        const newline = carry.indexOf(`
`);
        if (newline >= 0)
          try {
            ready = JSON.parse(carry.slice(0, newline));
          } catch {
            faults.push("stand-ready-frame");
          }
      }
    });
  child.on("exit", (code, why) => {
    exitObserved = true;
    exitCode = code;
    signal = why;
  });
  const closed = new Promise((resolve27) => child.on("close", () => {
    closeObserved = true;
    resolve27();
  }));
  child.on("error", (error) => faults.push(error.name));
  for (let step = 0;step < 600 && !ready && !closeObserved; step++)
    await Bun.sleep(100);
  const origin = "http://127.0.0.1:" + (ready?.port ?? 0);
  const call = async (path, body, timeoutMs = path === "/up" || path === "/close" ? 600000 : 120000) => {
    const response = await infrastructureHttpFetch(origin + path, { method: "POST", headers: {
      "content-type": "application/json",
      "X-ObjRun-Grader-Token": options.token
    }, body: JSON.stringify(body) }, timeoutMs);
    const raw = await response.text();
    demand(Buffer.byteLength(raw) <= 2 * 1024 ** 2, "tb12_stand_response_limit");
    if (!response.ok)
      throw Error("Owned stand " + response.status + " " + path + " " + raw);
    return JSON.parse(raw);
  };
  const finishCapture = () => {
    const stdout = join31(options.output, "stand.stdout"), stderr = join31(options.output, "stand.stderr");
    writeFileSync12(stdout, Buffer.concat(chunks[0]), { flag: "wx" });
    writeFileSync12(stderr, Buffer.concat(chunks[1]), { flag: "wx" });
    return durable3(join31(options.output, "stand-close.json"), {
      protocol: "tb12-stand-native-close-v1",
      pid: child.pid,
      argv: [python, ...args],
      port: ready?.port ?? null,
      startedAtUtc: start,
      closedAtUtc: new Date().toISOString(),
      exitObserved,
      closeObserved,
      exitCode,
      signal,
      faults,
      stdout: actualPin(stdout),
      stderr: actualPin(stderr),
      script: actualPin(options.script),
      python: actualPin(python),
      standReceipt: existsSync11(join31(options.output, "stand/stand-receipts.json")) ? actualPin(join31(options.output, "stand/stand-receipts.json")) : null,
      tokenExcluded: true
    });
  };
  if (!(ready?.protocol === "tb12-stand-ready-v1" && ready.pid === child.pid && ready.modelCalls === 0 && !faults.length)) {
    if (!closeObserved) {
      child.kill("SIGKILL");
      await Promise.race([closed, Bun.sleep(5000)]);
    }
    finishCapture();
    throw Error("tb12_stand_actual_startup");
  }
  return {
    origin,
    pid: child.pid,
    port: ready.port,
    call,
    isClosed: () => closeObserved,
    waitForClose: () => closed,
    async close() {
      let closeError, actorsAbsent = false;
      try {
        const result = await call("/close", {});
        actorsAbsent = result.allExactOwnedActorsAbsent === true;
      } catch (error) {
        closeError = error;
      }
      await Promise.race([closed, Bun.sleep(30000)]);
      if (!closeObserved && actorsAbsent) {
        child.kill("SIGKILL");
        await Promise.race([closed, Bun.sleep(5000)]);
        faults.push("stand_close_timeout");
      }
      if (closeError || !actorsAbsent) {
        faults.push("stand_close_without_actor_absence");
        finishCapture();
        throw Object.assign(new Error("stand_close_requires_owned_actor_reconciliation"), { childPid: child.pid, closeObserved });
      }
      demand(exitObserved && closeObserved && exitCode === 0 && !faults.length, "tb12_stand_exit_and_close");
      return finishCapture();
    }
  };
}

// scripts/benchmark-campaign/full-f/terminal-bench/gzip-train-fasttext-image-pool-custody.next.ts
init_paid_resource_proof_v2();
import { gunzipSync as gunzipSync5 } from "zlib";
import { createHash as createHash7 } from "crypto";
import { copyFileSync, existsSync as existsSync12, mkdirSync as mkdirSync14, readFileSync as readFileSync19, linkSync, lstatSync as lstatSync5, realpathSync as realpathSync5 } from "fs";
import { basename as basename10, dirname as dirname13, join as join33, resolve as resolve28 } from "path";

// scripts/terminal-bench-repair/tb12-v2/freeze_sources.ts
init_paid_resource_proof_v2();
import { basename as basename9, dirname as dirname12, join as join32, resolve as resolve27 } from "path";
var ROOT11 = resolve27(import.meta.dir, "../../..");

// scripts/benchmark-campaign/full-f/terminal-bench/gzip-train-fasttext-image-pool-custody.next.ts
var root3 = resolve28(import.meta.dir, "../../../..");
var home = join33(root3, "docs/repair-2026-10-10/full-f-rerun/terminal-bench");
var poolBase = join33(home, "private-context-v1/immutable-official-image-gzip-parts");
function immutableImagePartEligible(pin) {
  const path = resolve28(pin.path), parent = dirname13(path);
  if (dirname13(parent) !== poolBase || !/^[a-f0-9]{64}$/.test(basename10(parent)) || !/^part-[0-9]{4}-[a-f0-9]{64}\.bin\.gz$/.test(basename10(path)))
    return false;
  demand(!lstatSync5(path).isSymbolicLink() && realpathSync5(path) === path, "image_pool_scope");
  const record = JSON.parse(readFileSync19(join33(parent, "pool-manifest.json"), "utf8"));
  demand(record.complete === true && record.purpose === "immutable_original_official_image_export_gzip_parts" && record.concatenatedSha256 === basename10(parent), "image_pool_purpose");
  const nativePin = record.originalNativeImportProofPin;
  verifyPin(nativePin);
  demand(resolve28(nativePin.path) === join33(home, "private-context-v1/official-train-fasttext-blobs/import-proof.json"), "image_pool_native_proof_scope");
  const native = jsonPin(nativePin);
  demand(native.complete && native.actualDockerImportValidated && native.actualConfigSha256MatchesSource && native.actualRootFSDiffIdsMatchSource && native.actualPlatformAndExecutionConfigMatchSource, "image_pool_native_identity");
  demand(native.exportedDockerArchivePin.sha256 === record.concatenatedSha256 && native.exportedDockerArchivePin.bytes === record.concatenatedBytes, "image_pool_original_export");
  demand(record.orderedPartPins.some((p) => same(p, pin)) && pin.bytes <= 128 * 1024 ** 2, "image_pool_part_attestation");
  verifyPin(pin);
  const decoded = record.decodedPartProofs.find((row) => row.compressedPartSha256 === pin.sha256);
  demand(decoded && decoded.decodedBytes <= 64 * 1024 ** 2, "image_pool_decoded_bound");
  const raw = gunzipSync5(readFileSync19(path), { maxOutputLength: 64 * 1024 ** 2 });
  demand(raw.length === decoded.decodedBytes && createHash7("sha256").update(raw).digest("hex") === decoded.decodedSha256, "image_pool_decoded_sha");
  return true;
}
function snapshotSources(output, pins) {
  const folder = join33(output, "source-snapshots");
  mkdirSync14(folder, { recursive: true });
  const links = [];
  const files = pins.map((originalPin) => {
    verifyPin(originalPin);
    const path = join33(folder, originalPin.sha256 + "-" + basename10(originalPin.path));
    if (!existsSync12(path)) {
      if (immutableImagePartEligible(originalPin)) {
        linkSync(originalPin.path, path);
        links.push({ originalPin, path, kind: "immutable_image_hardlink" });
      } else
        copyFileSync(originalPin.path, path);
    }
    const snapshotPin = actualPin(path);
    demand(snapshotPin.sha256 === originalPin.sha256, "tb12_source_snapshot_changed");
    return { originalPin, snapshotPin };
  });
  const target = join33(folder, "manifest.json");
  if (existsSync12(target)) {
    const pin = actualPin(target);
    demand(same(jsonPin(pin).files, files), "tb12_source_snapshot_reuse_changed");
    return pin;
  }
  durable3(join33(folder, "immutable-image-custody.json"), { protocol: "terminal-immutable-original-image-custody-v1", links, mutableEvidenceHardlinked: false });
  return durable3(target, { protocol: "tb12-matching-executed-source-snapshots-v1", files });
}

// scripts/benchmark-campaign/full-f/terminal-bench/segment-scope.ts
function segmentScope(planned, ready) {
  if (planned.length !== 89 || new Set(planned).size !== 89)
    throw new Error("Full Terminal-Bench plan must retain 89 unique tasks");
  if (!ready.length || new Set(ready).size !== ready.length || ready.some((id) => !planned.includes(id)))
    throw new Error("Ready segment must be a nonempty unique subset of the full plan");
  return { plannedTaskRuns: 89, taskIds: [...planned], executingTaskIds: [...ready], pendingPreparationTaskIds: planned.filter((id) => !ready.includes(id)) };
}

// scripts/benchmark-campaign/full-f/terminal-bench/engine-task-id.ts
import { createHash as createHash8 } from "crypto";
function engineTaskId(runId, arm, officialTaskId) {
  if (!runId || arm !== "F" || !officialTaskId)
    throw Error("terminal_engine_task_id_input");
  return "tb12-" + createHash8("sha256").update(JSON.stringify([runId, arm, officialTaskId])).digest("hex").slice(0, 32);
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/campaign.ts
var ROOT12 = "F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin";
var SIX = ["bash", "read", "write", "edit", "glob", "grep"];
function objective(stand) {
  return {
    nodes: [
      { name: "ran", domain: "bool", moment: "done", handle: stand + "/ran" },
      { name: "passed", domain: "bool", moment: "done", handle: stand + "/passed" }
    ],
    edges: [{ src: "ran", out: 0, dst: "passed" }],
    sink: "passed",
    checks: 4,
    reuse: "never"
  };
}
async function executeFullF(options) {
  const output = resolve29(options.output);
  mkdirSync15(output, { recursive: true });
  const sourceGuard = () => {
    Bun.gc(true);
    if (!options.initialDelivery)
      for (const pin of options.sourcePins)
        verifyPin(pin);
    options.admission?.assertOwned();
  };
  for (const pin of options.sourcePins)
    verifyPin(pin);
  sourceGuard();
  snapshotSources(output, options.sourcePins);
  const baseProof = options.readinessPath ?? join34(ROOT12, "docs/repair-2026-10-10/full-f-rerun/terminal-bench/private-scoring-ready.json");
  const context = jsonPin(actualPin(jsonPin(actualPin(baseProof)).contextManifest.path));
  const taskIds = options.kind === "local-mock" ? options.coldTaskIds ?? ["chess-best-move"] : options.realTaskIds ?? context.tasks.map((task) => task.taskId);
  const scope = segmentScope(context.tasks.map((task) => task.taskId), taskIds);
  if (taskIds.length !== 89) {
    const ready = jsonPin(actualPin(baseProof));
    demand(!!options.readinessPath && ready.protocol === "terminal-ready-segment-v1" && ready.fullPlanTaskCount === 89 && JSON.stringify(ready.readyTaskIds) === JSON.stringify(taskIds), "terminal_ready_segment_proof");
  }
  const selected = context.tasks.filter((task) => taskIds.includes(task.taskId));
  demand(selected.length === taskIds.length, "tb12_task_selection");
  const graderToken = randomBytes6(32).toString("hex");
  const secrets = options.secrets ?? new Set;
  secrets.add(graderToken);
  if (options.providerKey)
    secrets.add(options.providerKey);
  const routeProvider = options.provider ?? (options.kind === "real-provider" ? BENCHMARK_PROVIDER2 : undefined);
  const model = routeProvider?.model ?? "deepseek-flash", keyEnv = routeProvider ? "OPENROUTER_API_KEY" : "DEEPSEEK_API_KEY";
  const provider = providerGateway({ ...options, provider: routeProvider, sourceGuard });
  secrets.add(provider.token);
  let stand;
  let machine;
  const records = [], engineClosures = [];
  let fatal = null, standClose, financialClose, bundle;
  const boardHashes = new Map;
  try {
    bundle = await freezeEngine(join34(output, "frozen-engine"));
    stand = await startStand({ output: join34(output, "stand-process"), script: join34(import.meta.dir, "stand_entry_runpy.py"), baseProof, token: graderToken });
    process.env.TGENGIN_GRADER_TOKEN = graderToken;
    process.env.TGENGIN_GRADER_ORIGINS = stand.origin;
    durable3(join34(output, "manifest.json"), {
      protocol: "tb12-paired-trial-manifest-v1",
      family: TB12_FAMILY,
      runId: options.runId,
      providerKind: options.kind,
      ...scope,
      arms: ["F"],
      replica: 0,
      model,
      provider: routeProvider?.kind ?? "deepseek-direct",
      providerName: routeProvider?.providerName,
      providerSlug: routeProvider?.providerSlug,
      currency: routeProvider ? "USD" : "CNY",
      ...BENCHMARK_INFERENCE2,
      thinking: { type: "enabled" },
      maxTokensPerRequest: BENCHMARK_INFERENCE2.maxTokens,
      checks: 4,
      reuse: "never",
      maxBranches: 1,
      maxDeadSiblings: 1,
      maxUnitsPerCycle: 32,
      taskDeadlines: context.tasks.map((task) => ({ taskId: task.taskId, agentSeconds: task.agentSeconds, verifierSeconds: task.verifierSeconds })),
      officialScope: actualPin(join34(ROOT12, "docs/repair-2026-10-10/full-f-rerun/terminal-bench/manifest.json")),
      contextManifest: actualPin(jsonPin(actualPin(baseProof)).contextManifest.path),
      baseProof: actualPin(baseProof),
      sourcePins: options.sourcePins,
      hostBun: actualPin(process.execPath),
      hostBunVersion: Bun.version,
      bundle,
      oldSingleNginxCounts: false,
      fullRunAuthorized: true,
      pairedOrder: "fixed public task order; F only",
      gradedInterface: "sealed regular data; untrusted OpenSSL script worker; narrow live nginx",
      feedback: "ran/passed booleans with generic failure note; no private assertions in model context",
      namespaceAndClockMeasuredBeforeAnyModel: true,
      paidConcurrency: 1,
      executionRevision: "terminal-only-seal-v2",
      sealPolicy: "after actual task terminal and no pending provider transfer; before engine close and host final grade",
      initialDelivery: options.initialDelivery ?? false,
      fullIndependentReviewDeferred: options.initialDelivery ?? false,
      operationalCaptureLimitBytes: 2 * 1024 ** 2,
      officialStorageBytes: 10240 * 1024 ** 2,
      perContainerStorageQuotaEnforced: false,
      storageBoundaryPolicy: "user authorized no per-container quota or writable-layer hard stop; shared disk floor and resource lease retained",
      diskQuotaEnforced: false,
      writableLayerHardLimitBytes: null,
      diskQuotaChangeUserAuthorized: true,
      guestAvailableStorageMeasuredBeforeAnyModel: true
    });
    for (const task of selected)
      for (const arm of ["F"]) {
        sourceGuard();
        const index = records.length, id = engineTaskId(options.runId, arm, task.taskId), place = "tb12:" + id;
        const route = options.runId + "/" + arm + "/0/" + task.taskId;
        const up = await stand.call("/up", { place, attemptId: id, taskId: task.taskId, arm });
        let board;
        if (up.publicImage?.exists) {
          board = actualPin(up.publicImage.stored);
          demand(board.sha256 === up.publicImage.sha256, "tb12_public_board_integrity");
          const prior = boardHashes.get(task.taskId);
          if (prior)
            demand(prior === board.sha256, "tb12_paired_image_changed");
          else
            boardHashes.set(task.taskId, board.sha256);
        }
        provider.register(route, task.taskId, arm, board);
        const engineDirectory = join34(output, "workers", String(index) + "-" + arm);
        machine = await startEngine({
          directory: engineDirectory,
          bundle: bundle.executable,
          proxyKey: provider.token,
          graderToken,
          graderOrigins: [stand.origin],
          onSecret: (value) => secrets.add(value)
        });
        await machine.api("POST", "/exec", {
          sql: "insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select :key,:model,handle,modes,:base,'[]' from api where key_env=:key and model=:seed",
          params: { key: keyEnv, model, seed: routeProvider ? model : "deepseek-v4-flash", base: provider.origin + "/" + route + "/v1" }
        });
        const verifierMs = (task.verifierSeconds + 30) * 1000, toolMs = (task.agentSeconds + 30) * 1000;
        await machine.api("POST", "/declare", {
          handles: [
            { name: stand.origin + "/place", expectMs: toolMs },
            ...["ran", "passed"].map((node) => ({ name: stand.origin + "/" + node, expectMs: verifierMs }))
          ],
          places: [{ place, identity: stand.origin + "/place", forward: true, tools: SIX.map((tool) => ({ tool, policy: "always" })) }],
          modes: [{ mode: "repair_tb12", cycles: [
            { cycle: "ask", apiMode: "chat", maxUnits: 32, from: [], next: ["act"], infer: "fn:infer.dfs" },
            { cycle: "act", maxUnits: 32, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }
          ] }],
          agents: [{ name: "bot", apis: [[keyEnv, model]], unit: "fn:unit.tools" }]
        });
        await alignToolUnitBudget(machine, toolMs, join34(engineDirectory, "tool-unit-envelope.json"));
        await machine.api("POST", "/exec", { sql: "update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit','verify')" });
        const publicRoot = join34(ROOT12, ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks", task.taskId);
        const instruction = readFileSync20(join34(publicRoot, "instruction.md"), "utf8");
        const prompt = instruction + `

Every bash/read/write/edit/glob/grep call runs inside your task container. Submit the completed filesystem or service state; your answer is only an attempt label. Official tests remain outside your container. Use verify only when offered.`;
        const started = Date.now();
        await stand.call("/begin", { place });
        await machine.api("POST", "/tasks", {
          id,
          run: options.runId,
          mode: "repair_tb12",
          agent: "bot",
          place,
          source: "user",
          domain: "software",
          workdir: "/app",
          description: prompt,
          ...arm === "F" ? { objective: objective(stand.origin), readable: false } : {},
          solveSeconds: task.agentSeconds,
          maxBranches: 1,
          maxDeadSiblings: 1,
          noSearch: ["terminal-bench solution", task.taskId + " solution"]
        });
        let result, sealed = false;
        const expiry = started + (task.agentSeconds + task.verifierSeconds * 5 + 120) * 1000;
        while (Date.now() < expiry) {
          sourceGuard();
          let standState;
          for (let probe = 0;probe < 3; probe++) {
            try {
              standState = JSON.parse(readFileSync20(join34(output, "stand-process/stand/stand-receipts.json"), "utf8"));
              break;
            } catch (error) {
              if (!(error instanceof SyntaxError))
                throw error;
              if (probe === 2)
                throw Error("terminal_stand_receipt_unreadable_after_bounded_retry");
              await Bun.sleep(25);
            }
          }
          if (standState.fatal) {
            provider.seal(route);
            if (!(provider.pending.get(route) ?? 0))
              throw Error("terminal_stand_fault_admission_closed:" + standState.fatal.type);
            await Bun.sleep(250);
            continue;
          }
          const state = await machine.api("GET", "/tasks/" + encodeURIComponent(id));
          const verdict = state.result ? JSON.parse(String(state.result)) : null;
          if (["done", "failed"].includes(state.state) && !["finalization_pending", "finalization_error"].includes(verdict?.outcome) && !(provider.pending.get(route) ?? 0)) {
            result = state;
            provider.seal(route);
            if (!sealed) {
              await stand.call("/seal", { place }, verifierMs + 30000);
              sealed = true;
            }
            break;
          }
          if (provider.fault())
            throw Error(provider.fault());
          await Bun.sleep(250);
        }
        demand(result, "tb12_actual_task_terminal_required");
        const engineClose = await machine.stop();
        engineClosures.push(engineClose);
        machine = undefined;
        const db = new Database(join34(engineDirectory, "data/h2h.sqlite"), { readonly: true });
        let candidate;
        let trace, units;
        try {
          trace = { rows: db.query("select * from agent_bot_msg where instance like ? order by unit,seq").all(id + "#%") };
          units = { rows: db.query("select * from agent_bot_ctx where instance like ? order by unit").all(id + "#%") };
          demand(units.rows.every((unit) => Number(unit.done) === 1), "tb12_unfinished_execution_unit");
          candidate = finalCandidate({
            all: (sql, params) => db.query(sql).all(...params ?? []),
            run() {
              throw Error("readonly");
            },
            exec() {
              throw Error("readonly");
            },
            close() {}
          }, id);
        } finally {
          db.close();
        }
        const calls = provider.calls.filter((call) => call.route === route);
        const tools = trace.rows.filter((row) => row.kind === "tool").map((row) => ({ at: Number(row.at), ...JSON.parse(String(row.body)) }));
        const firstSubmit = tools.filter((row) => row.name === "submit").sort((a, b) => a.at - b.at)[0];
        const repairedAfterFailedSubmit = !!firstSubmit && tools.some((row) => row.name === "write" && row.at > firstSubmit.at && !row.value?.error);
        if (options.kind === "local-mock" && arm === "F")
          demand(repairedAfterFailedSubmit, "tb12_actual_F_post_submit_repair_required");
        const runtimeVerdict = result.result ? JSON.parse(String(result.result)) : { valid: true, outcome: "unaided_generated" };
        const generation = classifyGeneration({ runtimeVerdict, state: String(result.state), calls, trace: trace.rows, candidate: candidate?.body });
        const deadline = Number(result.created_at) + Number(result.solve_seconds) * 1000;
        const lateMutation = trace.rows.some((row) => {
          if (row.kind !== "tool" || Number(row.at) <= deadline)
            return false;
          try {
            return ["bash", "write", "edit"].includes(JSON.parse(String(row.body)).name);
          } catch {
            return false;
          }
        });
        if (generation.valid && lateMutation) {
          generation.kind = "experimental_failure";
          generation.outcome = "budget_exhausted";
          generation.why = "A mutation completed after the official task deadline.";
        }
        const record = {
          index,
          family: TB12_FAMILY,
          runId: options.runId,
          officialId: task.taskId,
          arm,
          replica: 0,
          taskId: id,
          place,
          candidateCid: up.cid,
          startedAtUtc: new Date(started).toISOString(),
          createdAt: result.created_at,
          deadlineUnixMs: deadline,
          agentSeconds: task.agentSeconds,
          verifierSeconds: task.verifierSeconds,
          promptSha256: hash(prompt),
          answer: candidate?.body ?? "",
          candidateHow: candidate?.how ?? "none",
          candidateLabelSha256: hash(candidate?.body ?? ""),
          generation,
          generationValid: generation.valid,
          state: result.state,
          runtimeVerdict,
          engineClosePin: engineClose,
          trace: trace.rows,
          units: units.rows,
          calls,
          publicImagePin: board ?? null,
          lateMutation,
          sealedBeforeHostFinalGrade: true,
          hostEngineClosedBeforeFinalGrade: true,
          repairedAfterFailedSubmit,
          executionRevision: "terminal-only-seal-v2"
        };
        durable3(join34(output, "task-" + index + ".json"), record);
        sourceGuard();
        record.acceptance = generation.valid && generation.kind === "experimental_failure" ? { valid: true, passed: false, outcome: generation.outcome, why: generation.why, candidateSha256: record.candidateLabelSha256, nodes: {} } : await gradeFixedCandidate({
          objective: objective(stand.origin),
          task: result,
          candidate: candidate?.body,
          expectedCandidateSha256: record.candidateLabelSha256,
          generation,
          timeoutMs: verifierMs
        });
        sourceGuard();
        durable3(join34(output, "task-" + index + ".json"), record, true);
        records.push({ index: record.index, acceptance: record.acceptance });
        await stand.call("/stop", { place });
        options.onRecord?.(record);
        durable3(join34(output, "summary.json"), {
          protocol: "tb12-paired-operational-summary-v1",
          family: TB12_FAMILY,
          runId: options.runId,
          providerKind: options.kind,
          ...scope,
          recordedTaskRuns: records.length,
          operationalComplete: false,
          fatal: null,
          taskPins: records.map((row) => actualPin(join34(output, "task-" + row.index + ".json")))
        }, true);
        console.log(JSON.stringify({
          taskId: task.taskId,
          arm,
          valid: record.acceptance.valid,
          passed: record.acceptance.passed,
          modelRequests: options.kind === "real-provider" ? calls.filter((call) => call.providerAttempted).length : 0
        }));
        if (!generation.valid || record.acceptance.valid !== true)
          throw Error("tb12_invalid_generation_or_grading_record");
      }
  } catch (error) {
    fatal = error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : String(error);
  } finally {
    if (machine)
      try {
        engineClosures.push(await machine.stop());
        machine = undefined;
      } catch (error) {
        fatal ??= String(error);
      }
    if (stand)
      try {
        standClose = await stand.close();
        stand = undefined;
      } catch (error) {
        fatal ??= String(error);
      }
    try {
      await provider.stop();
      financialClose = provider.close();
    } catch (error) {
      fatal ??= String(error);
    }
  }
  const segmentComplete = !fatal && campaignComplete(taskIds.length, records);
  const complete = !fatal && campaignComplete(scope.plannedTaskRuns, records);
  const summary = durable3(join34(output, "summary.json"), {
    protocol: "tb12-paired-operational-summary-v1",
    family: TB12_FAMILY,
    runId: options.runId,
    providerKind: options.kind,
    ...scope,
    recordedTaskRuns: records.length,
    segmentComplete,
    operationalComplete: complete,
    formalScoreCertified: false,
    fatal,
    engineClosures,
    standClose: standClose ?? null,
    financialClose: financialClose ?? null,
    taskPins: records.map((row) => actualPin(join34(output, "task-" + row.index + ".json"))),
    modelCalls: options.kind === "real-provider" ? provider.calls.filter((call) => call.providerAttempted).length : 0,
    oldNginxIncluded: false,
    fullPlanActivated: true,
    fullRunExecuted: complete
  }, true);
  return { summary, complete, segmentComplete, fatal, engineClosures, standClose, financialClose };
}

// scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_3/versions/pipeline-wx-v50/worker.ts
var root4 = "F:/git/TgEngin-handoff-2026-10-07/TgEngin";
var tid = "torch-pipeline-parallelism";
var home2 = join35(root4, "docs/repair-2026-10-10/full-f-rerun/terminal-bench");
var campaignRoot = join35(root4, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013");
var own = join35(campaignRoot, "group-04/adapter_3/versions/pipeline-wx-v50");
var mode = process.argv[2];
demand(["--local", "--check", "--run"].includes(mode), "pipeline_explicit_mode_required");
var rp = resolve30(process.argv[3] ?? join35(own, "readiness.json"));
var pp = resolve30(process.argv[4] ?? join35(own, "task-plan.json"));
demand(rp.startsWith(resolve30(own) + sep) && pp.startsWith(resolve30(own) + sep), "pipeline_owned_entry_paths");
var ready = JSON.parse(readFileSync21(rp, "utf8"));
var plan = JSON.parse(readFileSync21(pp, "utf8"));
var manifest = JSON.parse(readFileSync21(join35(home2, "manifest.json"), "utf8"));
validateIsolatedJobs(manifest, plan);
demand(plan.jobs.length === 1 && plan.jobs[0].taskId === tid, "pipeline_single_job");
verifyPin(plan.jobs[0].readinessPin);
verifyPin(plan.manifestPin);
demand(ready.protocol === "terminal-ready-segment-v1" && ready.fullPlanTaskCount === 89 && JSON.stringify(ready.readyTaskIds) === JSON.stringify([tid]) && ready.readyForRootReview === true && ready.qualificationOnly !== true, "pipeline_full89_single_scope");
demand(ready.requiredResourceMemoryMb === 24576 && ready.requiredResourceGrowthBytes === 32212254720 && plan.jobs[0].originalPeakMemoryMb === 16384 && plan.jobs[0].originalPlannedGrowthBytes === 10737418240, "pipeline_original_aggregate_budget");
var pins = [...ready.runtimeSourcePins, ...ready.taskEvidencePins, ready.contextManifest, ready.imagesPin, ready.qualificationPin, actualPin(rp), actualPin(pp), plan.manifestPin];
for (const p of pins)
  verifyPin(p);
for (const task of manifest.records)
  for (const p of task.sourceFiles)
    verifyPin(p);
var context = JSON.parse(readFileSync21(ready.contextManifest.path, "utf8"));
demand(context.tasks.length === 89 && new Set(context.tasks.map((t) => t.taskId)).size === 89, "pipeline_context_full89");
var task = context.tasks.find((x) => x.taskId === tid);
demand(task.agentSeconds === 900 && task.verifierSeconds === 900 && task.officialEnvironment.cpus === 1 && task.officialEnvironment.memory_mb === 8192, "pipeline_original_clocks_actor");
demand(BENCHMARK_PROVIDER2.model === "deepseek/deepseek-v4.1-flash" && BENCHMARK_PROVIDER2.providerSlug === "digitalocean" && BENCHMARK_INFERENCE2.reasoningEffort === "high", "pipeline_solver_fixed");
var ep = join35(own, "entry.json");
var authPath = process.argv[5] ? resolve30(process.argv[5]) : undefined;
var reviewed = false;
if (authPath && existsSync14(authPath)) {
  demand(authPath.startsWith(resolve30(campaignRoot, "coordinator") + sep), "pipeline_root_authorization_location");
  const auth = JSON.parse(readFileSync21(authPath, "utf8"));
  for (const key of ["entryPin", "sourceManifestPin", "qualificationPin", "readinessPin", "taskPlanPin"])
    verifyPin(auth[key]);
  demand(auth.rootReviewed === true && auth.rootOnlyDispatch === true && auth.taskId === tid && auth.allowPaid === true && auth.narrowCompositeApproved === true && auth.productionAuditContractReviewed === true, "pipeline_root_narrow_authorization_required");
  demand(auth.entryPin.sha256 === actualPin(ep).sha256 && auth.readinessPin.sha256 === actualPin(rp).sha256 && auth.taskPlanPin.sha256 === actualPin(pp).sha256 && auth.sourceManifestPin.sha256 === ready.sourceManifestPin.sha256 && auth.qualificationPin.sha256 === ready.qualificationPin.sha256, "pipeline_signed_exact_entry");
  reviewed = true;
}
if (mode !== "--run") {
  console.log(JSON.stringify({ protocol: "pipeline-wx-v50-pure-preflight", staticPassed: true, planned: 89, executingTaskIds: [tid], readyForRootReview: true, formalReady: reviewed, rootReviewed: reviewed, modelCalls: 0, newPaidRequests: 0, dockerActions: 0, resourceAcquisitions: 0 }));
  process.exit(0);
}
demand(reviewed && process.env.NOVAEVE_ROOT_ONLY_DISPATCH === "1", "pipeline_unsigned_or_nonroot_run_denied_before_any_native_paid_action");
var audit = JSON.parse(readFileSync21(join35(home2, "actual-run-audit.json"), "utf8"));
demand(!audit.tasks.some((x) => x.officialId === tid) && !audit.runs.some((x) => (x.requests ?? []).some((q) => q.taskId === tid)), "pipeline_prior_paid_attempt_never_repeat");
var connection = await boundConnection(root4);
function disk() {
  const p = join35(campaignRoot, "broker/remote-disk.json"), d = JSON.parse(readFileSync21(p, "utf8"));
  demand(d.protocol === "novaeve-runtime-disk-v1" && d.dataRoot === "/data/wpx/tgengin/docker" && Date.now() - d.observedAtMs >= 0 && Date.now() - d.observedAtMs <= 1e4 && d.freeBytes >= 5 * 1024 ** 3, "pipeline_remote_disk_fresh_floor");
}
disk();
var resource = await acquireResource(root4);
try {
  disk();
  const runs = join35(home2, "runs");
  mkdirSync16(runs, { recursive: true });
  const { runId, output } = await reserveIsolatedRunDirectory(root4, runs);
  const sourcePins = [...pins, actualPin(ep), actualPin(authPath)];
  const admission = await acquireFullFAdmission({ root: root4, output, runId, slug: "terminal-bench", sourcePins, connection });
  const processPath = join35(output, "process.json");
  writeFileSync13(processPath, JSON.stringify({ pid: process.pid, runId, output, taskId: tid, rootAuthorizationPin: actualPin(authPath), planned: 89, executingTaskIds: [tid], arms: ["F"] }) + `
`, { flag: "wx" });
  await admission.registerOwnedProcess(actualPin(processPath));
  const result = await executeFullF({ kind: "real-provider", provider: BENCHMARK_PROVIDER2, runId, output, prices: admission.prices, sourcePins, admission, providerKey: randomBytes7(24).toString("hex"), ownerForwardGuard: beforePipelineForward, transport: (raw) => admission.transport(raw), readinessPath: rp, realTaskIds: [tid] });
  demand(result.financialClose?.cashClose, "pipeline_cash_close");
  const close = inspectFullFClosedCash(root4, result.financialClose.cashClose);
  demand(close.accountingClosed, "pipeline_accounting_close");
  await admission.finishLightweight({ cashPin: result.financialClose.cashClose, summaryPin: result.summary });
  console.log(JSON.stringify({ runId, output, segmentComplete: result.segmentComplete, planned: 89, executed: 1 }));
  process.exitCode = result.segmentComplete ? 0 : 2;
} finally {
  await resource.release();
}
