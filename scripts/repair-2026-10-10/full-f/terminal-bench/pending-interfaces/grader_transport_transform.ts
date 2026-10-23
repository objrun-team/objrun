/** Bench-owned transform: retain the declared grader deadline, remove the
 * unrelated Bun socket idle limit only for authenticated grader origins. */
export function graderTransportSource(source:string){
 const replace=(before:string,after:string)=>{if(source.split(before).length!==2)throw Error('grader_transport_source_shape:'+before);source=source.replace(before,after);};
 replace('function remote(url: string): Handle {','function remote(url: string, timeoutMs = 120000): Handle {');
 replace('call: remote(r.name) }','call: remote(r.name, r.expect_ms) }');
 replace('body: JSON.stringify(arg ?? {}),','body: JSON.stringify(arg ?? {}),\n      signal: AbortSignal.timeout(timeoutMs),');
 replace('...(trusted ? { redirect: "error" } : {})','...(trusted ? { redirect: "error", timeout: false } : {})');
 return source;
}
