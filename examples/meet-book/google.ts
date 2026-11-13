/**
 * Create a Google Meet and obtain its booking link. **Both approaches share this file.**
 *
 * Two operations: `authStart` starts authorization, and `book` creates a meeting. Authorization is itself a tool, not a separate preparatory script: when unauthorized, the model calls it, gives the user the link, then continues after the user clicks.
 *
 * ## Required files
 *
 * | | |
 * | --- | --- |
 * | `~/.tgengin/client_secret.json` | A **desktop application** OAuth client downloaded from Google Cloud Console |
 * | `~/.tgengin/google.json` | Created automatically after authorization |
 *
 * The client is unavoidable: it identifies the application requesting permission, not the user.
 *
 * ## Why keep pending state?
 *
 * Authorization requires a human click. A tool call is a request/response exchange and cannot wait for a person indefinitely. `authStart` starts a callback listener and **immediately returns the link**; `authWait` wakes when the user completes the flow. This pending state lives in process memory: the Worker for the in-process approach, the child process for the external approach. Each owns its state; neither needs database storage.
 */

import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { mkdir } from "node:fs/promises";

const CLIENT_FILE = process.env.TGENGIN_GOOGLE_CLIENT ?? join(homedir(), ".tgengin", "client_secret.json");
const TOKEN_FILE = process.env.TGENGIN_GOOGLE_TOKEN ?? join(homedir(), ".tgengin", "google.json");
const CAL = "https://www.googleapis.com/calendar/v3";

/** Creating meetings writes to the calendar; readonly access is insufficient. */
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
  if (!(await f.exists())) throw new Error(`no OAuth client: ${CLIENT_FILE}`);
  const c = (await f.json()) as { installed?: { client_id: string; client_secret: string } };
  if (!c.installed) throw new Error(`${CLIENT_FILE} is not a desktop application (the top level must be "installed")`);
  return c.installed;
}

async function creds(): Promise<Creds | null> {
  const f = Bun.file(TOKEN_FILE);
  if (!(await f.exists())) return null;
  const c = (await f.json()) as Partial<Creds>;
  if (!c.client_id || !c.client_secret || !c.refresh_token) return null;
  return c as Creds;
}

/** The `token` (access token) expires after one hour. Obtain a fresh one each time instead of caching, removing one piece of expiring state. */
async function accessToken(): Promise<string> {
  const c = await creds();
  if (!c) throw new Error("not authorised yet");
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
    throw new Error(`cannot exchange for an access token: ${got.error_description ?? got.error ?? res.status}`);
  }
  return got.access_token;
}

// ── Authorization ──

let pending: { url: string; done: Promise<void> } | null = null;

/** Check authorization by actually exchanging refresh_token; if the exchange fails, treat it as unauthorized. */
export async function authed(): Promise<boolean> {
  try {
    await accessToken();
    return true;
  } catch {
    return false;
  }
}

/**
 * Start authorization. **Return immediately**, without waiting for the user to click.
 *
 * Use port 0 so the OS chooses a free port, allowing both approaches to run without collisions. Desktop clients accept any loopback port, so preregistration is unnecessary.
 */
export async function authStart(): Promise<{ ok: boolean; authUrl?: string; note: string }> {
  if (await authed()) return { ok: true, note: "already authorised - go ahead and book" };
  if (pending) return { ok: false, authUrl: pending.url, note: "the last link has not been clicked yet - this is it" };

  const { client_id, client_secret } = await client();
  let settle: (() => void) | null = null;
  const done = new Promise<void>((r) => (settle = r));

  const server = Bun.serve({
    port: 0,
    // Specify the return type: this method is named fetch and calls global fetch inside. Without the annotation,
    // TypeScript thinks it is inferring its own type recursively.
    async fetch(req: Request): Promise<Response> {
      const u = new URL(req.url);
      const code = u.searchParams.get("code");
      if (!code) return new Response(`no good: ${u.searchParams.get("error") ?? "no code came back"}`);
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
        return new Response(`cannot exchange for a refresh_token: ${got.error_description ?? res.status}`);
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
      return new Response("Authorised. Go back and carry on.", { headers: { "content-type": "text/plain; charset=utf-8" } });
    },
  });

  const auth = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  auth.search = new URLSearchParams({
    client_id,
    redirect_uri: `http://localhost:${server.port}`,
    response_type: "code",
    scope: SCOPE,
    access_type: "offline",
    prompt: "consent", // Without this, the second authorization does not return a refresh_token.
  }).toString();

  pending = { url: auth.toString(), done };
  return { ok: false, authUrl: pending.url, note: "hand this link to the user; once clicked, it is done" };
}

/** Wait for the user to finish. Return true immediately if already authorized, or false if authorization was never started. */
export async function authWait(ms: number): Promise<boolean> {
  if (await authed()) return true;
  const p = pending;
  if (!p) return false;
  const raced = await Promise.race([p.done.then(() => true), Bun.sleep(ms).then(() => false)]);
  return raced;
}

// ── Create a meeting ──

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
 * Create a meeting. `minutesFromNow` is the delay before it starts; `minutes` is its duration.
 *
 * `waitAuthMs` sets how long to wait if authorization is pending. On timeout, raise an error so the model calls the authorization tool.
 *
 * Without `conferenceDataVersion=1`, Google silently drops the entire `conferenceData`: the event is created without a meeting link and no error is reported.
 */
export async function book(
  a: { summary?: string; minutesFromNow?: number; minutes?: number; attendees?: string[] },
  waitAuthMs = 180_000,
): Promise<Booked> {
  if (!(await authed())) {
    const got = await authWait(waitAuthMs);
    if (!got) throw new Error("not authorised yet - call the authorisation tool first and have the user click the link");
  }
  const token = await accessToken();
  const startsIn = Number(a.minutesFromNow ?? 10);
  const lasts = Number(a.minutes ?? 30);
  const start = new Date(Date.now() + startsIn * 60_000);
  const end = new Date(start.getTime() + lasts * 60_000);
  const summary = a.summary?.trim() || "Meeting";

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
  if (!res.ok) throw new Error(`Google refused to create it: ${body.error?.message ?? res.status}`);

  // The meeting link is created asynchronously. Usually it is available immediately; if pending, query again a few times.
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
    throw new Error(`the event was created (${e.id}) but no meeting link grew on it (${st})`);
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

// ── Schemas shown to the model. Both approaches expose the same schemas. ──

export const LOGIN_DOES = "Start Google authorisation. Returns a link for the user to click in a browser";
export const LOGIN_PARAMS = { type: "object", properties: {} } as const;
export const LOGIN_OUTPUT = {
  type: "object",
  properties: { ok: { type: "boolean" }, authUrl: { type: "string" }, note: { type: "string" } },
} as const;

export const BOOK_DOES = "Book a meeting under the Google account signed in on this machine; returns the Meet link and the calendar event";
export const BOOK_PARAMS = {
  type: "object",
  properties: {
    summary: { type: "string", description: "Meeting title" },
    minutesFromNow: { type: "integer", description: "How many minutes from now it starts, default 10" },
    minutes: { type: "integer", description: "How long it runs, default 30" },
    attendees: { type: "array", items: { type: "string" }, description: "Attendee email addresses" },
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
