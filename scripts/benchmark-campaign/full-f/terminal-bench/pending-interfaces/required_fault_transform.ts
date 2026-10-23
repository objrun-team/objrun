/** Next-build cleanup for a completed, rejected mandatory-tool response.
 * Keeps actual response/cost/stuck evidence, marks protocol failure invalid.
 * Not applied to any running engine or shared/app source.
 */
export function requiredFaultSource(source:string){
  const marker='const why = msg(e);\n      const serviceError =';
  if(source.split(marker).length!==2)throw Error('required_fault_kernel_shape');
  const cleanup=`const why = msg(e);
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
  return source.replace(marker,cleanup);
}
