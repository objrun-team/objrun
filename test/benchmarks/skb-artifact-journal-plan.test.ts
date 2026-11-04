import { describe, expect, test } from 'bun:test';
import { hash } from '../../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import { assertSkbArtifactSchedule, fixedSkbArtifactSchedule, loadSkbArtifactSelection, rawFrontmatterBody, SKB_ARTIFACT_IDS } from '../../scripts/benchmark-repair/skb-artifact-journal-contract.ts';

describe('new prospective SkillsBench ten-task contract',()=>{
  test('actual frozen ten-task source trees and raw bodies match prior independent metadata',()=>{
    const v=loadSkbArtifactSelection();expect(v.tasks.map(t=>t.taskId)).toEqual([...SKB_ARTIFACT_IDS]);expect(v.sourceTaskCount).toBe(87);expect(v.selectedTaskCount).toBe(10);expect(v.unselectedTaskCount).toBe(77);
    expect(v.tasks.every(t=>t.originalResources.environment.storage_mb===10240)).toBe(true);
  });
  test('fixed20 preserves paired bodies and task-specific original resources',()=>{
    const v=loadSkbArtifactSelection(),id='repair-2026-10-09T08-00-00-000Z',rows=fixedSkbArtifactSchedule(id,v.tasks);
    expect(rows.length).toBe(20);expect(new Set(rows.map(r=>r.officialId)).size).toBe(10);
    for(const task of v.tasks){const pair=rows.filter(r=>r.officialId===task.taskId);expect(pair.map(r=>r.arm)).toEqual(['U','F']);expect(pair[0]!.promptBodySha256).toBe(pair[1]!.promptBodySha256);expect(pair.every(r=>r.taskSeconds===task.originalResources.agent.timeout_sec&&r.verifierSeconds===task.originalResources.verifier.timeout_sec&&r.cpus===task.originalResources.environment.cpus&&r.memoryMb===task.originalResources.environment.memory_mb)).toBe(true);}
    expect(rows.find(r=>r.officialId==='econ-detrending-correlation')!.verifierSeconds).toBe(240);expect(rows.find(r=>r.officialId==='lab-unit-harmonization')!.verifierSeconds).toBe(1800);expect(rows.find(r=>r.officialId==='lab-unit-harmonization')!.taskSeconds).toBe(1800);
    expect(()=>assertSkbArtifactSchedule(id,rows,v.tasks,hash(JSON.stringify(rows)))).not.toThrow();
    expect(()=>assertSkbArtifactSchedule(id,rows.slice(2),v.tasks,hash(JSON.stringify(rows.slice(2))))).toThrow('skb_frozen_twenty_task_runs');
    const changed=structuredClone(rows);changed[0]!.taskSeconds=1800;expect(()=>assertSkbArtifactSchedule(id,changed,v.tasks,hash(JSON.stringify(changed)))).toThrow('skb_frozen_twenty_task_runs');
  });
  test('exact extraction keeps CRLF, whitespace, Unicode and later delimiter',()=>{
    const body='\r\n 示例  \r\n---\r\nend\r\n';expect(rawFrontmatterBody(Buffer.from('---\r\nagent: {}\r\n--- \t\r\n'+body))).toBe(body);
    expect(()=>rawFrontmatterBody(Buffer.from('missing frontmatter'))).toThrow('skb_raw_frontmatter_delimiters');expect(()=>rawFrontmatterBody(Uint8Array.of(0xff))).toThrow();
  });
});
