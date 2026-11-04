/** End a stranded native HTTP request only after provider calls have settled. */
export function nativeInterfaceTimedOut(why: any, pendingProxyRequests: number): boolean {
  if (pendingProxyRequests !== 0) return false;
  return (why?.problems ?? []).some((problem: unknown) =>
    /kernel threw while advancing/i.test(String(problem)) &&
    /operation timed out|fetch failed|socket.*closed|connection.*closed/i.test(String(problem)));
}
