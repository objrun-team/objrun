from pathlib import Path
p=Path(__file__).parent
for old,new in [('broker-adoption-v46.ts','broker-adoption-v48.ts'),('sign-adoption-v46.ts','sign-adoption-v48.ts'),('preflight-adoption-v46.ts','preflight-adoption-v48.ts'),('start-adoption-v46.ts','start-adoption-v48.ts'),('adopted-parent-v46.ts','adopted-parent-v48.ts')]:
 s=(p/old).read_text()
 for a,b in [('broker-adoption-v46','broker-adoption-v48'),('sign-adoption-v46','sign-adoption-v48'),('preflight-adoption-v46','preflight-adoption-v48'),('adopted-parent-v46','adopted-parent-v48'),('root-reviewed-broker-adoption-v46','root-reviewed-broker-adoption-v48'),('root-signed-adoption-v46','root-signed-adoption-v48'),('root-adopted-resource-closure-v46','root-adopted-resource-closure-v48'),('truthful-broker-adoption-v46','truthful-broker-adoption-v48'),('broker-adoption-v46-','broker-adoption-v48-')]:s=s.replace(a,b)
 if new=='adopted-parent-v48.ts':
  s="import {inspectZeroNewLaneState} from './zero-new-lane-state-v48.ts';\n"+s
  needle='const ownerGuardPin=claimUniqueAdoption'
  insert="const restart=jsonPin(plan.restartProofPin);for(const p of [...restart.durablePins,plan.previousAdoptionGuardPin])verifyPin(p);const current=inspectZeroNewLaneState(restart.previousDirectory);demand(same(current,restart),'durable_restart_state_changed');const previousState=jsonPin(restart.allocationPin);\n "
  s=s.replace(needle,insert+needle)
  a=s.index('let state={protocol:');b=s.index(';const statePath=',a)
  s=s[:a]+"let state={...previousState,protocol:'novaeve-adopted-allocation-v48',previousAllocationPin:restart.allocationPin,previousSignedPlanPin:restart.previousSignedPlanPin,newLanes:{} as any}"+s[b:]
  s=s.replace('historicalDelegatedExecutorPid:466248,','historicalDelegatedExecutorPid:466248,previousAdoptedExecutorPid:1304,previousSignedAdoptionPlanPin:restart.previousSignedPlanPin,previousAdoptionGuardPin:plan.previousAdoptionGuardPin,')
  s=s.replace('proof.originalGlobalDelegationGuardPin,...plan.sourcePins','proof.originalGlobalDelegationGuardPin,plan.previousAdoptionGuardPin,...restart.durablePins,...plan.sourcePins')
 if new=='preflight-adoption-v48.ts':
  s="import {inspectZeroNewLaneState} from './zero-new-lane-state-v48.ts';\n"+s
  s=s.replace("for(const p of [plan.rehydrateProofPin,...plan.sourcePins])verifyPin(p);","for(const p of [plan.rehydrateProofPin,plan.restartProofPin,plan.previousAdoptionGuardPin,...plan.sourcePins])verifyPin(p);const restart=jsonPin(plan.restartProofPin);if(JSON.stringify(inspectZeroNewLaneState(restart.previousDirectory))!==JSON.stringify(restart))throw Error('actual_previous_durable_state_changed');")
 if (p/new).exists():raise RuntimeError('WX source exists '+new)
 (p/new).write_text(s)
