/**
 * A human-facing page **served by the engine itself** at `/ui`, without a separate build or installation.
 *
 * ## Just another client
 *
 * It uses only endpoints in `api/`, never database tables. State values and message kinds
 * are fetched from `/about` at startup rather than hard-coded, so new server-side values become
 * available automatically. As described in `api/about.ts`, clients consume these as data,
 * not copied constants.
 *
 * ## Why embed the page instead of shipping an adjacent file
 *
 * In a compiled executable, `import.meta.dir` is a virtual path without files, as discussed in
 * `tools/python.ts`. Importing the HTML as text bundles it into the executable, so source and
 * compiled execution serve the same page.
 *
 * ## Token
 *
 * The page itself is exempt from authentication (`public` in `H2H/server.ts`) because it contains
 * code, not data. Every data request still carries `Authorization`; users enter the token in the UI.
 */

import type { FastifyInstance } from "fastify";

import raw from "./index.html" with { type: "text" };

// bun-types declares `*.html` as an HTMLBundle for `Bun.serve`. Importing with
// `with { type: "text" }` returns a string at runtime, so explicitly state that type here.
const PAGE = raw as unknown as string;

/** Page path. Like `/help`, it is a fixed application endpoint, not a configurable value. */
export const UI_PATH = "/ui";

/**
 * Install the page, embedding the API prefix so it never has to guess endpoint locations.
 * Return the mount path so startup logging can print its full URL.
 */
export function mountUi(app: FastifyInstance, prefix: string): string {
  const page = PAGE.replaceAll("__PREFIX__", prefix);
  app.get(UI_PATH, async (_req, reply) => reply.type("text/html; charset=utf-8").send(page));
  return UI_PATH;
}
