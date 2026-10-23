from pathlib import Path
p=Path(__file__).parent
f=p/'adopted-consumer-guard-v48.ts';s=f.read_text();a=s.index(' for(const h of healths){');b=s.index('\n // Independently',a)
block=s[a:b];body=block[len(' for(const h of healths){'):-1]
body=body.replace('parent.capUsd','proof.originalCapUsd')
s=s[:a]+" for(const h of healths)assertLiveAdoptionSnapshot(h,connection,proof,owner);"+s[b:]
needle='export async function verifyAdoptedConnection'
s=s.replace(needle,"export function assertLiveAdoptionSnapshot(h:any,connection:any,proof:any,owner:any){"+body+"}\n"+needle)
f.write_text(s)
