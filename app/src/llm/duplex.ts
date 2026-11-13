/**
 * Realtime track (duplex): a WebSocket session.
 *
 * ## How it differs from chat
 *
 * Chat maps one call to one execution unit; the connection ends with the call. Duplex is **a session, not one call**: each execution unit corresponds to **one exchange**, while the session spans several units.
 *
 * The **handle signature is identical to chat**: the kernel passes a unit and receives the row to store. The kernel neither knows nor should know about sessions; otherwise `cycle.api_mode` would serve no purpose.
 *
 * ## A session is a connection, not state
 *
 * Sessions live in an in-process pool, **not the database**, just as `workplace.usable` is a declaration rather than a health probe. Persisting session liveness would leave stale claims after a crash and restart.
 *
 * What the database preserves is **every exchange**: the model's speech, other participants' speech, and tool requests all enter `agent_<name>_msg`. After a crash the session is gone but the record survives, preserving the database-as-snapshot property.
 *
 * ## DashScope uses beta event names
 *
 * This is **the most important detail here**. Qwen's realtime endpoint uses OpenAI's *beta* event schema, while common current names follow *GA*. A mismatch produces no error: **nothing is received**. The connection remains open and events flow, but no handler claims them, so an exchange never finishes.
 *
 * Map inbound names from beta to GA through {@link BETA2GA} before dispatch. **Map inbound events only**: outbound events retain beta names because that is what the endpoint accepts.
 *
 * ## The receive loop must never die
 *
 * The old implementation failed here three times, each silently rather than with an error:
 *
 * 1. Beta `response.done` lacked usage; reading `usage.input_tokens` caused a NoneType failure that **killed the entire receiver coroutine**, silencing all subsequent events.
 * 2. An undecodable event was skipped without clearing response state. "Still speaking" remained true forever, so the session went silent after one utterance.
 * 3. A participant-transcription event used the beta schema and was skipped when decoding failed, losing all user speech.
 *
 * The resulting rule: **an undecodable event may discard only itself, never the connection**, and discarded events must be **counted**. Silent failures look like nothing happened. Without counts, future event-name drift would appear merely as an unusually quiet model.
 *
 * ## Scope of this implementation
 *
 * **Protocol only: text input, text and transcription output.**
 *
 * Audio capture and playback belong to devices. Every audio I/O library introduces native dependencies, violating the zero-native, cross-compilation requirement. Audio integration is deferred and will sit above this layer.
 *
 * Output audio is **discarded immediately and counted, never stored**. Saving byte streams in `agent_<name>_msg` would inflate snapshots to hundreds of MB with an unreadable column. **Transcriptions are the trajectory.**
 */

import type { Conn } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { deliver } from "../msg/deliver.ts";
import { RETRY_ON, SERVES, VENDORS, instructionsOf, sendable, type Unit, viewOf } from "./index.ts";

/**
 * Sessions that have already received the task view.
 *
 * Sessions are **live resources**, like locations, so this set also lives in memory rather than the database. A process exit destroys the sessions; a newly opened one naturally receives the view again.
 */
const seenView = new Set<string>();

/**
 * Inbound event names: beta → GA. **Copied unchanged from the old code's table.**
 *
 * Omitting a mapping leaves that event type permanently unhandled, silently. Extra mappings are harmless, so retain the full list.
 */
export const BETA2GA: Record<string, string> = {
  "response.audio.delta": "response.output_audio.delta",
  "response.audio_transcript.delta": "response.output_audio_transcript.delta",
  "response.text.delta": "response.output_text.delta",
  "conversation.item.created": "conversation.item.added",
  "response.audio.done": "response.output_audio.done",
  "response.audio_transcript.done": "response.output_audio_transcript.done",
  "response.text.done": "response.output_text.done",
};

/**
 * Hard wall-clock limit for one exchange.
 *
 * Chat allows 15 minutes because one call may produce a complete essay. A duplex exchange is a short utterance; two minutes already indicates trouble. Without a limit, the session and row could wait forever until `expect_ms` marks it dead, leaving no diagnostic clues.
 */
export const TURN_MS = 120_000;

/** Deadline for connecting and receiving `session.created`. Report failure immediately instead of hanging. */
export const OPEN_MS = 20_000;

/**
 * Idle lifetime before reclaiming a session.
 *
 * Sessions follow an `instance`, but nothing announces instance completion. **Without reclamation they leak**: an open WebSocket keeps consuming provider capacity. Compute idleness from time since last use instead of adding timers; scanning whenever a session is opened is sufficient.
 */
export const IDLE_MS = 300_000;

/** Modes supported by this handle. **Only duplex**: it does not implement request-response chat. */
const SERVED = new Set(["duplex"]);

/**
 * Request text only.
 *
 * Audio is not integrated yet (see the header), so requesting it would discard the output while still paying for audio tokens.
 * When the device layer arrives, change this single definition rather than duplicating settings at call sites.
 */
const MODALITIES = ["text"];

/**
 * Accumulated data for one exchange.
 *
 * Collect `errors` rather than throwing immediately: provider errors need not be fatal (even committing an empty audio buffer produces one). **With output, treat the exchange as successful; without output, use errors as the cause**. This avoids killing a unit for an irrelevant error while retaining more than a generic "nothing returned" when it truly fails.
 */
interface Turn {
  text: string[];
  calls: { id: string; name: string; input: unknown }[];
  /** Discarded audio-chunk count. **Count, do not store**; see the header. */
  audio: number;
  errors: string[];
  settle(e: Error | null): void;
}

/** The result of a completed exchange. */
export interface TurnOut {
  /** Model speech, combining text deltas and speech-transcription deltas. */
  text: string;
  calls: { id: string; name: string; input: unknown }[];
  /** Discarded audio-chunk count. */
  audio: number;
  /** Provider-reported errors. **Not a failure cause when output exists**; retained for the record. */
  errors: string[];
  /** Transcribed **speech from others** during this exchange. The handle stores it; the session does not access the database. */
  heard: string[];
  /** Cumulative skipped-event count for this session. **Event-name drift first appears as growth in this number.** */
  skipped: number;
}

/** An item sent into the session. `type` uses the provider's item shape, not our message-table format. */
type Item = Record<string, unknown>;

/**
 * Bun's `WebSocket` accepts options as its second argument (the browser version accepts a subprotocol).
 *
 * **Realtime credentials must use request headers**; without them the connection fails. This cast is necessary, not a shortcut. Define it once instead of casting independently at every call site.
 */
type WithHeaders = new (url: string, opts: { headers: Record<string, string> }) => WebSocket;

/** One session. **Understands the protocol, not the database**; persistence belongs to the handle layer. */
export class Session {
  readonly model: string;
  /** Time of last use, used to compute idle reclamation without a separate timer. */
  used = Date.now();
  /** Count of undecodable or unhandled events. **The only clue to silent drift**, so always expose it. */
  skipped = 0;
  /** Observed inbound event names. If names change, this list supplies evidence. */
  readonly seen = new Set<string>();

  #ws: WebSocket;
  #turn: Turn | null = null;
  #dead: Error | null = null;
  /** Provider transcriptions of **other participants' speech**. The handle drains and stores them after each exchange. */
  #heard: string[] = [];
  /** item_id → tool-call identity. Some implementations supply the name only in the item event, so retain it. */
  #fn = new Map<string, { name: string; call: string }>();
  #ready: Promise<void>;

  constructor(url: string, key: string, model: string) {
    this.model = model;
    const Ws = WebSocket as unknown as WithHeaders;
    this.#ws = new Ws(`${url}?model=${encodeURIComponent(model)}`, {
      headers: { Authorization: `Bearer ${key}` },
    });

    this.#ready = new Promise<void>((ok, fail) => {
      const wall = setTimeout(() => fail(new Error(`opening the realtime session took over ${OPEN_MS}ms with no session.created`)), OPEN_MS);
      this.#opened = () => {
        clearTimeout(wall);
        ok();
      };
      this.#ws.addEventListener("error", () => fail(this.#dead ?? new Error("cannot reach the realtime session")));
      this.#ws.addEventListener("close", () => fail(this.#dead ?? new Error("the realtime session closed before it opened")));
    });

    this.#ws.addEventListener("message", (e: MessageEvent) => this.#take(String(e.data)));
    // A disconnected socket means an in-flight exchange will never receive response.done. **Finalize it immediately**.
    // Otherwise it waits until TURN_MS, and the log cannot distinguish disconnection from a silent provider.
    this.#ws.addEventListener("close", () => this.#die(new Error("the realtime session dropped")));
    this.#ws.addEventListener("error", () => this.#die(new Error("the realtime session dropped on an error")));
  }

  #opened: () => void = () => {};

  /** Whether the session is ready. Fail here if opening fails, rather than delaying until the first send. */
  ready(): Promise<void> {
    return this.#ready;
  }

  get dead(): Error | null {
    return this.#dead;
  }

  #die(e: Error): void {
    if (!this.#dead) this.#dead = e;
    this.#turn?.settle(e);
  }

  #send(o: Record<string, unknown>): void {
    if (this.#dead) throw this.#dead;
    this.#ws.send(JSON.stringify(o));
  }

  /**
   * Receive one event. **This function must not throw.**
   *
   * The old code died at this layer: a malformed event payload raised an exception that killed the receiver coroutine. The connection stayed open and events kept flowing, but nothing was processed. **The symptom was silence, not an error**, leaving diagnosis to guesswork.
   *
   * Dispatch **only by `type`**. Malformed payloads affect only that event. Even if dispatch fails, still finalize `response.done`; otherwise this exchange can never complete.
   */
  #take(raw: string): void {
    this.used = Date.now();
    let d: Record<string, unknown>;
    try {
      d = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      this.skipped++;
      return;
    }
    const beta = String(d.type ?? "");
    this.seen.add(beta);
    // **Map inbound names only.** Outbound events retain beta names, the only schema the endpoint accepts.
    const type = BETA2GA[beta] ?? beta;
    try {
      this.#dispatch(type, d);
    } catch (e) {
      this.skipped++;
      this.#turn?.errors.push(`cannot handle ${beta}: ${e instanceof Error ? e.message : String(e)}`);
      if (type === "response.done") this.#turn?.settle(null);
    }
  }

  /** Recognized events. **Names use GA**; inbound names have already been mapped. */
  #dispatch(type: string, d: Record<string, unknown>): void {
    switch (type) {
      case "session.created":
        this.#opened();
        return;

      // Received with no action required. **Still list these explicitly**: falling through to default would inflate `skipped`.
      // That number is the only clue to event-name drift; normal events would make it useless.
      case "session.updated":
      case "response.created":
      case "response.output_item.added":
      case "response.output_item.done":
      case "response.content_part.added":
      case "response.content_part.done":
      case "response.output_text.done":
      case "response.output_audio.done":
      case "response.output_audio_transcript.done":
      case "conversation.item.done":
      case "input_audio_buffer.speech_started":
      case "input_audio_buffer.speech_stopped":
      case "input_audio_buffer.committed":
      case "rate_limits.updated":
        return;

      // Model speech. Text deltas and transcription deltas are **two sources for the same trajectory**, accumulated together.
      // Listening to only one would yield no content after changing modalities.
      case "response.output_text.delta":
      case "response.output_audio_transcript.delta":
        this.#turn?.text.push(String(d.delta ?? ""));
        return;

      // Audio is **discarded immediately and only counted**. As explained above, byte streams bloat snapshots; transcriptions are the trajectory.
      case "response.output_audio.delta":
        if (this.#turn) this.#turn.audio++;
        return;

      case "conversation.item.added": {
        const item = (d.item ?? {}) as Record<string, unknown>;
        if (item.type === "function_call" && item.id) {
          this.#fn.set(String(item.id), {
            name: String(item.name ?? ""),
            call: String(item.call_id ?? item.id),
          });
        }
        return;
      }

      case "response.function_call_arguments.done": {
        // The tool name may be absent here; some implementations provide it only in the item event. Check both.
        // If neither has it, fail rather than proceeding with an empty name and appearing to call a nonexistent tool.
        const itemId = String(d.item_id ?? "");
        const known = this.#fn.get(itemId);
        const name = String(d.name ?? known?.name ?? "");
        const call = String(d.call_id ?? known?.call ?? itemId);
        if (!name) throw new Error(`a tool call did not name a tool (item_id=${itemId})`);
        this.#turn?.calls.push({ id: call, name, input: JSON.parse(String(d.arguments ?? "{}")) });
        return;
      }

      // Previously observed failure: this event uses the beta schema, and a generic parser **skipped the entire event** on failure.
      // That silently lost other participants' speech. Handle it explicitly.
      case "conversation.item.input_audio_transcription.completed": {
        const said = String(d.transcript ?? "").trim();
        if (said) this.#heard.push(said);
        return;
      }

      // The exchange has ended. **Only this event establishes completion.**
      // Previously observed failure: the beta event lacked usage, and reading metrics crashed. Read no payload fields here; finalization only finalizes.
      case "response.done":
        this.#turn?.settle(null);
        return;

      case "error":
        this.#turn?.errors.push(errText(d));
        return;

      default:
        // Unknown events are not errors (providers may add new ones), but count them.
        // Event-name drift first appears as growth in this number.
        this.skipped++;
    }
  }

  /**
   * Initial setup: send instructions and tool declarations.
   *
   * **Send once**: the session remembers. This distinguishes it from chat, which must resend instructions per unit because the provider has no previous turn.
   */
  async update(instructions: string, tools: Item[]): Promise<void> {
    await this.ready();
    this.#send({
      type: "session.update",
      session: {
        modalities: MODALITIES,
        ...(instructions ? { instructions } : {}),
        ...(tools.length ? { tools, tool_choice: "auto" } : {}),
      },
    });
  }

  /**
   * Perform one exchange: send these items and wait for speech to finish.
   *
   * **A session is sequential; exchanges must run one after another.** Tree siblings can make several units of the same instance runnable concurrently, and the kernel advances them in parallel. Sending them concurrently into one session would mix their events **without errors**, giving each half of the other's speech. Queue them here.
   */
  turn(items: Item[]): Promise<TurnOut> {
    const go = () => this.#one(items);
    const next = this.#queue.then(go, go);
    // A failed exchange must not break the queue and cause every subsequent unit to fail with it.
    this.#queue = next.then(
      () => {},
      () => {},
    );
    return next;
  }

  #queue: Promise<unknown> = Promise.resolve();

  async #one(items: Item[]): Promise<TurnOut> {
    await this.ready();
    if (this.#dead) throw this.#dead;

    const t: Turn = { text: [], calls: [], audio: 0, errors: [], settle: () => {} };
    const wait = new Promise<void>((ok, fail) => {
      // Hard deadline. **Without it this row would hang** until the kernel marks it dead under expect_ms,
      // leaving no diagnostic clues, not even the provider's reported errors.
      const wall = setTimeout(() => {
        const why = t.errors.length ? `; the far side reported: ${t.errors.join("; ")}` : "";
        fail(new Error(`a turn took over ${TURN_MS}ms with no response.done${why}`));
      }, TURN_MS);
      let settled = false;
      t.settle = (e) => {
        if (settled) return; // Ignore duplicate response.done events.
        settled = true;
        clearTimeout(wall);
        if (e) fail(e);
        else ok();
      };
    });

    this.#turn = t; // Attach the receiver before sending, or the first events will have no listener.
    try {
      for (const it of items) this.#send({ type: "conversation.item.create", item: it });
      this.#send({ type: "response.create" });
      await wait;
    } finally {
      this.#turn = null;
    }

    // Clear transcriptions after draining them; otherwise the next exchange would store the same speech again.
    return {
      text: t.text.join(""),
      calls: t.calls,
      audio: t.audio,
      errors: t.errors,
      heard: this.#heard.splice(0),
      skipped: this.skipped,
    };
  }

  close(): void {
    this.#dead ??= new Error("the session is already closed");
    try {
      this.#ws.close();
    } catch {
      // Closing an already disconnected socket is harmless.
    }
  }
}

function errText(d: Record<string, unknown>): string {
  const e = d.error;
  if (e !== null && typeof e === "object" && "message" in e) return String((e as { message: unknown }).message);
  return JSON.stringify(e ?? d);
}

/**
 * Database row → session item. Return `null` for rows that cannot or should not be sent.
 *
 * This and chat's `toMsg` are two representations of the same operation, **sharing the `sendable` criterion**. Separate copies would drift when rules for model-visible content change.
 */
function itemOf(r: { role: string; kind: string; body: string }, sentAs: Record<string, string>): Item | null {
  if (!sendable(r, sentAs)) return null;

  // The model's tool request from the previous exchange. **The session remembers its own speech**; resending would make it hear itself again.
  // Chat must resend because it has no previous turn. This is a concrete distinction between the tracks.
  if (r.kind === "call" || r.kind === "graded") return null;

  if (r.kind === "tool") {
    const v = JSON.parse(r.body) as { id?: string; value?: unknown };
    return { type: "function_call_output", call_id: v.id ?? "", output: JSON.stringify(v.value ?? null) };
  }
  if (r.role === "assistant") {
    return { type: "message", role: "assistant", content: [{ type: "text", text: r.body }] };
  }
  return { type: "message", role: "user", content: [{ type: "input_text", text: r.body }] };
}

/** A `tool` row → a session tool declaration. **Declare only; do not execute**, just as with chat. */
function toolOf(t: Record<string, unknown>): Item {
  return {
    type: "function",
    name: String(t.name),
    description: String(t.does ?? ""),
    parameters: JSON.parse(String(t.params)) as unknown,
  };
}

/**
 * Retain and reuse open sessions, like `Places` and for the same reason. Opening a new session for every execution unit would reduce duplex to chat and eliminate session memory.
 *
 * **Key by `(vendor, instance)`**: sessions follow agent instances. An instance's second unit continues its previous session, producing one session with multiple exchanges.
 */
export class Sessions {
  #open = new Map<string, Promise<Session>>();

  /** Current open-session count, for logs and inspection. */
  get size(): number {
    return this.#open.size;
  }

  get(vendor: string, instance: string, make: () => Promise<Session>): Promise<Session> {
    this.#reap();
    const k = `${vendor} ${instance}`;
    let s = this.#open.get(k);
    if (!s) {
      s = make();
      this.#open.set(k, s);
      // Remove a failed opening attempt so the next call can retry; retaining it would permanently break this instance.
      s.catch(() => this.#open.delete(k));
    }
    return s;
  }

  /**
   * Close sessions idle too long.
   *
   * Nothing announces instance completion. **Without reclamation sessions leak**: an open WebSocket consumes provider capacity indefinitely. Compute idleness from last use instead of starting timers; timers are extra in-memory state, while a scan on each session opening is sufficient.
   *
   * Remove disconnected sessions too, or the next unit would receive a dead session and fail immediately.
   */
  #reap(): void {
    const now = Date.now();
    for (const [k, p] of this.#open) {
      void p
        .then((s) => {
          if (s.dead !== null || now - s.used > IDLE_MS) {
            s.close();
            this.#open.delete(k);
          }
        })
        .catch(() => this.#open.delete(k));
    }
  }

  closeAll(): void {
    for (const p of this.#open.values()) void p.then((s) => s.close()).catch(() => {});
    this.#open.clear();
  }
}

/**
 * Register realtime tracks **only for providers with a `ws` address**. Registering a nonexistent realtime track would create an unusable handle, discovered only when execution reaches that station.
 *
 * The `api` rows in `seed` are **data**. Their `modes` is always `duplex`, the only shape this handle supports. Making it a parameter would only enable misconfiguration.
 */
export function registerDuplex(db: Conn, reg: Registry, pool: Sessions, seed: [string, string][]): string[] {
  const names: string[] = [];

  for (const [vendor, v] of Object.entries(VENDORS)) {
    if (!v.ws) continue; // This provider has no realtime track.
    const name = `fn:api.${vendor}.duplex`;
    SERVES.set(name, SERVED);
    names.push(name);

    // The limit applies to **one exchange**, not the entire session. Sessions may be long-lived; exchanges should not be.
    reg.register(db, name, TURN_MS, async (arg) => {
      const u = arg as unknown as Unit;
      if (!u.api) throw new Error(`${name} was called, but the kernel did not say which model this station uses`);
      const keyEnv = u.api.key_env;
      const secret = process.env[keyEnv];
      if (!secret) throw new Error(`no key in environment variable ${keyEnv} - see .env`);
      const model = u.api.model;
      // **Read the address from this row, not code.** Previously the closure used `VENDORS[vendor].ws`, so a different binary could send the same database to another endpoint, invalidating it as a snapshot.
      // `api.base_url` is now authoritative: this call goes where the row points.
      const ws = u.api.base_url;

      // The session follows the instance: its first unit opens the session and sends instructions; later units continue it.
      const s = await pool.get(vendor, u.instance, async () => {
        const fresh = new Session(ws, secret, model);
        await fresh.ready();
        await fresh.update(instructionsOf(u), u.tools.map(toolOf));
        return fresh;
      });

      // Put the task view first, as in chat: it defines the problem, and context follows it.
      // **Send only in the session's first exchange**. The session remembers; resending each round would repeat the problem many times.
      const view = viewOf(u);
      const opening: Item[] = view && !seenView.has(u.instance) ? [{ role: "user", text: view }] : [];
      if (opening.length) seenView.add(u.instance);

      const out = await s.turn([...opening, ...u.context.map((r) => itemOf(r, u.sentAs)).filter((x): x is Item => x !== null)]);

      // Store other participants' speech first, **through the sole delivery pipeline**. Infer kind and role there, not here.
      // Keep `voice` separate from `user`: transcription represents speech, not typing. Conflating them would replay transcriptions as typed input.
      for (const said of out.heard) {
        deliver(db, {
          agent: String(u.agent.name),
          instance: u.instance,
          unit: u.unit,
          by: "voice",
          body: said,
        });
      }

      // Use **exactly the same shape as chat**. Downstream persistence and tool execution share one contract.
      // Different return shapes would force them to know which track produced the result.
      if (out.calls.length > 0) {
        return {
          role: "assistant",
          kind: "call",
          body: JSON.stringify({ text: out.text, calls: out.calls }),
        };
      }

      if (out.text.trim() === "") {
        // An exchange ended with no text. **This is exactly what event-name drift looks like**.
        // Report all clues together: skipped-event count, observed event names, and provider errors. "Nothing returned" alone forces diagnosis from scratch.
        const why = [
          `${vendor}/${model} finished a turn but returned nothing`,
          `skipped ${out.skipped} events`,
          out.audio ? `dropped ${out.audio} audio chunks` : "",
          out.errors.length ? `the far side reported: ${out.errors.join("; ")}` : "",
          `event names seen: ${[...s.seen].join(", ") || "(none)"}`,
        ].filter(Boolean);
        throw new Error(why.join("; "));
      }

      return { role: "assistant", kind: "prompt", body: out.text };
    });
  }

  for (const [vendor, model] of seed) {
    const v = VENDORS[vendor];
    if (!v) throw new Error(`unknown vendor: ${vendor}`);
    if (!v.ws) throw new Error(`${vendor} has no realtime endpoint, so ${model} cannot get a duplex lane`);
    db.run(
      `insert into api (key_env, model, handle, modes, base_url, retry_on) values (?, ?, ?, 'duplex', ?, ?)
       on conflict(key_env, model) do update set handle = excluded.handle, modes = excluded.modes`,
      // Realtime uses `ws`, not this HTTP address. Fill `base_url` in this row so that
      // one api row always identifies its endpoint, with no exceptions.
      [v.keyEnv, model, `fn:api.${vendor}.duplex`, v.ws ?? v.baseURL, RETRY_ON],
    );
  }

  return names;
}
