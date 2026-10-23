/** Disable Bun idle timeout while retaining the caller's original wall deadline. */
export function infrastructureHttpFetch(url: string, init: RequestInit, wallTimeoutMs: number): Promise<Response> {
  if (!Number.isFinite(wallTimeoutMs) || wallTimeoutMs <= 0) throw Error('original_wall_deadline_required');
  return fetch(url, { ...init, signal: AbortSignal.timeout(wallTimeoutMs), ...{ timeout: false } });
}
