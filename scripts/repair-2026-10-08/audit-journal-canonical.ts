/** Streaming ECMAScript canonical check. Python independently checks duplicate keys and the byte hash chain. */
import { createReadStream } from "node:fs";
import { createHash } from "node:crypto";

export async function javascriptCanonicalJournal(path: string) {
  let pending = Buffer.alloc(0), bytes = 0, events = 0;
  const sha = createHash("sha256"), decoder = new TextDecoder("utf-8", { fatal: true });
  for await (const chunk of createReadStream(path, { highWaterMark: 65536 })) {
    const raw = Buffer.concat([pending, Buffer.from(chunk)]);
    let start = 0, end: number;
    while ((end = raw.indexOf(10, start)) !== -1) {
      const line = raw.subarray(start, end + 1);
      if (line.length > 65536) throw new Error("oversize_journal_event");
      const text = decoder.decode(line.subarray(0, -1)), value = JSON.parse(text);
      if (JSON.stringify(value) + "\n" !== decoder.decode(line)) throw new Error("noncanonical_javascript_event");
      sha.update(line); bytes += line.length; events++; start = end + 1;
    }
    pending = Buffer.from(raw.subarray(start));
    if (pending.length > 65536) throw new Error("oversize_journal_event");
  }
  if (pending.length) throw new Error("truncated_journal_event");
  return { valid: true, bytes, eventCount: events, fileSha256: sha.digest("hex"), runtime: Bun.version };
}
if (import.meta.main) {
  try { console.log(JSON.stringify(await javascriptCanonicalJournal(process.argv[2]))); }
  catch (error) { console.error(error instanceof Error ? error.message : "canonical_check_failed"); process.exitCode = 1; }
}
