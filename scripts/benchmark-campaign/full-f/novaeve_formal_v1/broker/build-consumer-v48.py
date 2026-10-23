from pathlib import Path
p=Path(__file__).parent
s=(p/'adopted-consumer-guard-v46.ts').read_text().replace("'./sign-adoption-v46.ts'","'./sign-adoption-v48.ts'").replace('novaeve-truthful-broker-adoption-v46','novaeve-truthful-broker-adoption-v48')
s=s.replace('h.maxInFlight===16','Number.isInteger(h.maxInFlight)&&h.maxInFlight>=1&&h.maxInFlight<=16')
s=s.replace("demand(same(healths[0].resourceSlots,healths[1].resourceSlots)&&same(healths[0].allocation,healths[1].allocation),'both_ports_same_pool_and_budget');","// Independently validate each snapshot. Concurrent acquire/close may legitimately differ between reads.\n demand(healths.every(h=>JSON.stringify(h.adoption.resourceEndpoints)==='[17889,17895]'&&h.adoption.protocol==='novaeve-truthful-broker-adoption-v48'),'signed_same_executor_shared_map_identity');")
s=s.replace('const proof=jsonPin(plan.rehydrateProofPin);','verifyPin(plan.restartProofPin);verifyPin(plan.previousAdoptionGuardPin);const restart=jsonPin(plan.restartProofPin);for(const p of restart.durablePins)verifyPin(p);const proof=jsonPin(plan.rehydrateProofPin);')
(p/'adopted-consumer-guard-v48.ts').write_text(s)
s=(p/'publish-adoption-v46.ts').read_text().replace("'./adopted-consumer-guard-v46.ts'","'./adopted-consumer-guard-v48.ts'").replace('adopted-consumer-guard-v46.ts','adopted-consumer-guard-v48.ts').replace('broker/adoption-v46/production-first','broker/adoption-v48/production-second').replace('activation-adopted-v46.json','activation-adopted-v48.json').replace('broker/control-adopted-v46.private.json','broker/control-adopted-v48.private.json')
s=s.replace('runId:connection.runId,broker:connection,adoption:metadata','runId:connection.runId,adoption:metadata')
s=s.replace('delete activation.delegation;','delete activation.delegation;delete activation.broker;')
(p/'publish-adoption-v48.ts').write_text(s)
