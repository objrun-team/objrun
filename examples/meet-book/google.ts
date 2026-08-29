/**
 * 开一个谷歌会议，拿预约链接。**两种写法共用这一个文件。**
 *
 * 两件事：`authStart` 发起授权，`book` 开会。授权不是拿脚本先跑一趟 ——
 * 它自己也是个工具，模型没授权的时候就调它，把链接给人，人点完接着干。
 *
 * ## 磁盘上要有的
 *
 * | | |
 * | --- | --- |
 * | `~/.tgengin/client_secret.json` | Google Cloud 控制台下的**桌面应用**类型 OAuth 客户端 |
 * | `~/.tgengin/google.json` | 授权之后自己长出来的 |
 *
 * 客户端那个躲不掉 —— 它是「哪个应用在要权限」，不是用户的东西。
 *
 * ## 为什么要留个 pending
 *
 * 授权中间隔着一次真人点击。工具调用是一来一回的，等不了人。所以 `authStart`
 * 起个回调监听就**马上回链接**，人什么时候点完，`authWait` 什么时候醒 ——
 * 这份 pending 活在进程内存里，进程内写法在 Worker 里，进程外写法在子进程里，
 * 两边各有各的，谁也不用落库。
 */

import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { mkdir } from "node:fs/promises";

const CLIENT_FILE = process.env.TGENGIN_GOOGLE_CLIENT ?? join(homedir(), ".tgengin", "client_secret.json");
const TOKEN_FILE = process.env.TGENGIN_GOOGLE_TOKEN ?? join(homedir(), ".tgengin", "google.json");
const CAL = "https://www.googleapis.com/calendar/v3";

/** 建会要写日历，光 readonly 不够。 */
export const SCOPE = "https://www.googleapis.com/auth/calendar.events";

interface Creds {
  client_id: string;
  client_secret: string;
  refresh_token: string;
  token_uri?: string;
}

export interface Booked {
  meetUrl: string;
  eventId: string;
  summary: string;
  start: string;
  end: string;
  htmlLink: string;
}

async function client(): Promise<{ client_id: string; client_secret: string }> {
  const f = Bun.file(CLIENT_FILE);
  if (!(await f.exists())) throw new Error(`没有 OAuth 客户端：${CLIENT_FILE}`);
  const c = (await f.json()) as { installed?: { client_id: string; client_secret: string } };
  if (!c.installed) throw new Error(`${CLIENT_FILE} 不是桌面应用类型（顶层得是 "installed"）`);
  return c.installed;
}

async function creds(): Promise<Creds | null> {
  const f = Bun.file(TOKEN_FILE);
  if (!(await f.exists())) return null;
  const c = (await f.json()) as Partial<Creds>;
  if (!c.client_id || !c.client_secret || !c.refresh_token) return null;
  return c as Creds;
}

/** `token`（access token）一小时就过期，所以每次现换一个，不缓存 —— 少一份会过期的状态。 */
async function accessToken(): Promise<string> {
  const c = await creds();
  if (!c) throw new Error("还没授权");
  const res = await fetch(c.token_uri ?? "https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: c.client_id,
      client_secret: c.client_secret,
      refresh_token: c.refresh_token,
      grant_type: "refresh_token",
    }),
  });
  const got = (await res.json()) as { access_token?: string; error?: string; error_description?: string };
  if (!res.ok || !got.access_token) {
    throw new Error(`换不到 access token：${got.error_description ?? got.error ?? res.status}`);
  }
  return got.access_token;
}

// ── 授权 ──────────────────────────────────────────────────────────────

let pending: { url: string; done: Promise<void> } | null = null;

/** 授权过没有 —— 拿 refresh_token 真换一次，换不动就当没授权。 */
export async function authed(): Promise<boolean> {
  try {
    await accessToken();
    return true;
  } catch {
    return false;
  }
}

/**
 * 发起授权。**马上回**，不等人点。
 *
 * 端口给 0，让系统挑一个空的 —— 两种写法同时跑也不会撞。桌面类型的客户端
 * 回环地址上什么端口都收，所以不用提前登记。
 */
export async function authStart(): Promise<{ ok: boolean; authUrl?: string; note: string }> {
  if (await authed()) return { ok: true, note: "已经授权过了，直接开会就行" };
  if (pending) return { ok: false, authUrl: pending.url, note: "上一次发的还没点，就是这个链接" };

  const { client_id, client_secret } = await client();
  let settle: (() => void) | null = null;
  const done = new Promise<void>((r) => (settle = r));

  const server = Bun.serve({
    port: 0,
    // 返回类型得写出来 —— 这个方法自己就叫 fetch，里面又调全局 fetch，不标的话
    // TS 认为它在推自己的类型。
    async fetch(req: Request): Promise<Response> {
      const u = new URL(req.url);
      const code = u.searchParams.get("code");
      if (!code) return new Response(`不行：${u.searchParams.get("error") ?? "没拿到 code"}`);
      const res = await fetch("https://oauth2.googleapis.com/token", {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          code,
          client_id,
          client_secret,
          redirect_uri: `http://localhost:${server.port}`,
          grant_type: "authorization_code",
        }),
      });
      const got = (await res.json()) as { refresh_token?: string; error_description?: string };
      if (!got.refresh_token) {
        return new Response(`换不到 refresh_token：${got.error_description ?? res.status}`);
      }
      await mkdir(dirname(TOKEN_FILE), { recursive: true });
      await Bun.write(
        TOKEN_FILE,
        JSON.stringify(
          { client_id, client_secret, refresh_token: got.refresh_token, token_uri: "https://oauth2.googleapis.com/token", scopes: [SCOPE] },
          null,
          2,
        ),
      );
      queueMicrotask(() => {
        server.stop();
        pending = null;
        settle?.();
      });
      return new Response("授权好了，回去接着干。", { headers: { "content-type": "text/plain; charset=utf-8" } });
    },
  });

  const auth = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  auth.search = new URLSearchParams({
    client_id,
    redirect_uri: `http://localhost:${server.port}`,
    response_type: "code",
    scope: SCOPE,
    access_type: "offline",
    prompt: "consent", // 不加的话第二次授权不给 refresh_token
  }).toString();

  pending = { url: auth.toString(), done };
  return { ok: false, authUrl: pending.url, note: "把这个链接给用户，点完就成了" };
}

/** 等人点完。已经授权的话立刻回 true；根本没发起过回 false。 */
export async function authWait(ms: number): Promise<boolean> {
  if (await authed()) return true;
  const p = pending;
  if (!p) return false;
  const raced = await Promise.race([p.done.then(() => true), Bun.sleep(ms).then(() => false)]);
  return raced;
}

// ── 开会 ──────────────────────────────────────────────────────────────

interface Event {
  id?: string;
  summary?: string;
  htmlLink?: string;
  hangoutLink?: string;
  start?: { dateTime?: string };
  end?: { dateTime?: string };
  conferenceData?: { createRequest?: { status?: { statusCode?: string } } };
}

/**
 * 开会。`minutesFromNow` 是几分钟之后开，`minutes` 是开多久。
 *
 * `waitAuthMs`：没授权但有人正在点的时候等多久。等不到就报错让模型去调授权那个。
 *
 * `conferenceDataVersion=1` 少一个，谷歌就把 `conferenceData` 整段吞了 ——
 * 事件建出来但没有会议链接，而且不报错。
 */
export async function book(
  a: { summary?: string; minutesFromNow?: number; minutes?: number; attendees?: string[] },
  waitAuthMs = 180_000,
): Promise<Booked> {
  if (!(await authed())) {
    const got = await authWait(waitAuthMs);
    if (!got) throw new Error("还没授权 —— 先调那个发起授权的工具，把链接给用户点一下");
  }
  const token = await accessToken();
  const startsIn = Number(a.minutesFromNow ?? 10);
  const lasts = Number(a.minutes ?? 30);
  const start = new Date(Date.now() + startsIn * 60_000);
  const end = new Date(start.getTime() + lasts * 60_000);
  const summary = a.summary?.trim() || "会议";

  const res = await fetch(`${CAL}/calendars/primary/events?conferenceDataVersion=1`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({
      summary,
      start: { dateTime: start.toISOString() },
      end: { dateTime: end.toISOString() },
      attendees: (a.attendees ?? []).map((email) => ({ email })),
      conferenceData: {
        createRequest: { requestId: crypto.randomUUID(), conferenceSolutionKey: { type: "hangoutsMeet" } },
      },
    }),
  });
  const body = (await res.json()) as Event & { error?: { message?: string } };
  if (!res.ok) throw new Error(`谷歌不给建：${body.error?.message ?? res.status}`);

  // 会议链接是异步长出来的。多数时候当场就有，pending 的话回头再问几次。
  let e = body;
  for (let i = 0; i < 5 && !e.hangoutLink; i++) {
    await Bun.sleep(600);
    const again = await fetch(`${CAL}/calendars/primary/events/${e.id}?conferenceDataVersion=1`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!again.ok) break;
    e = (await again.json()) as Event;
  }
  if (!e.hangoutLink) {
    const st = e.conferenceData?.createRequest?.status?.statusCode ?? "?";
    throw new Error(`事件建好了（${e.id}）但没长出会议链接（${st}）`);
  }

  return {
    meetUrl: e.hangoutLink,
    eventId: String(e.id),
    summary: e.summary ?? summary,
    start: e.start?.dateTime ?? start.toISOString(),
    end: e.end?.dateTime ?? end.toISOString(),
    htmlLink: e.htmlLink ?? "",
  };
}

// ── 给模型看的那几份 schema。两种写法报的是同一份。 ──────────────────────

export const LOGIN_DOES = "发起谷歌授权。回一个链接，让用户在浏览器里点一下";
export const LOGIN_PARAMS = { type: "object", properties: {} } as const;
export const LOGIN_OUTPUT = {
  type: "object",
  properties: { ok: { type: "boolean" }, authUrl: { type: "string" }, note: { type: "string" } },
} as const;

export const BOOK_DOES = "在本机这个谷歌账号下开一个会，返回 Meet 链接和日历事件";
export const BOOK_PARAMS = {
  type: "object",
  properties: {
    summary: { type: "string", description: "会议标题" },
    minutesFromNow: { type: "integer", description: "几分钟之后开，默认 10" },
    minutes: { type: "integer", description: "开多久，默认 30" },
    attendees: { type: "array", items: { type: "string" }, description: "参会人邮箱" },
  },
} as const;
export const BOOK_OUTPUT = {
  type: "object",
  properties: {
    meetUrl: { type: "string" },
    eventId: { type: "string" },
    summary: { type: "string" },
    start: { type: "string" },
    end: { type: "string" },
    htmlLink: { type: "string" },
  },
} as const;
