"""Benign explicit-load fixture: the signed binding must select the current guard."""
import adopted_owner_guard_v81 as guard

def observed():
 value=guard.guard()
 return {'guardPath':guard.__file__,'resourceLeasePid':value['resourceLeasePid'],'resourceMemoryMb':value['resourceMemoryMb'],'modelCalls':0}
