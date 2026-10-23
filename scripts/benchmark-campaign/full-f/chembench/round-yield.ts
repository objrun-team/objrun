import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
export type RoundHandoff={protocol:'chembench-round-handoff-v1';requestId:string;requested:boolean;brokerRunId:string;releaseAfterRound:number;runId?:string};
export function roundHandoffPending(request:RoundHandoff|undefined,context:{brokerRunId:string;round:number;runId?:string}){
  if(!request||!request.requested)return false;
  if(request.protocol!=='chembench-round-handoff-v1'||!request.requestId||!Number.isInteger(request.releaseAfterRound)||request.releaseAfterRound<1)throw Error('Invalid round handoff request');
  if(!context.brokerRunId||!Number.isInteger(context.round)||context.round<1)throw Error('Parent round evidence unavailable');
  return request.brokerRunId===context.brokerRunId&&context.round<=request.releaseAfterRound&&(!context.runId||!request.runId||request.runId===context.runId);
}
export function readRoundHandoff(out:string):RoundHandoff|undefined{
  const path=join(out,'round-handoff-request.json');
  return existsSync(path)?JSON.parse(readFileSync(path,'utf8').replace(/^\uFEFF/,'')):undefined;
}
