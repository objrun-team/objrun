"""Coalesce only overlapping exact-candidate /ran calls; consume original grade once."""
import copy,hashlib,threading,time

def _identity(stand,body):
 inp=body.get("input") or {};task=inp.get("task") or {};place=task.get("place");owner=stand.owner(place)
 assert task.get("id")==owner["attemptId"],"Grader attempt mismatch"
 result=inp.get("result");label=result.get("body") if isinstance(result,dict) else result
 label=str(label if label is not None else task.get("result","")).strip()
 return owner,place,label

def _note(stand,owner,place,current,kind):
 stand.rows.append({"kind":kind,"place":place,"attemptId":owner["attemptId"],"taskId":owner["taskId"],"invocationId":current.get("invocationId"),"labelSha256":hashlib.sha256(current["label"].encode()).hexdigest(),"registeredRanDeliveries":current["registered"],"passedDeliveries":current["delivered"],"newGradingInvocations":0})
 stand.persist()

def dispatch(stand,path,body,original):
 if path not in ("/ran","/passed"):return original(path,body)
 if stand.fatal:raise RuntimeError("Stand evidence fault has closed admission")
 owner,place,label=_identity(stand,body)
 state=owner.setdefault("_bench_grade_delivery_latch",{"lock":threading.RLock(),"current":None})
 with state["lock"]:
  current=state["current"]
  if path=="/ran":
   if current and current["phase"] in ("grading","ready"):
    assert current["label"]==label,"Previous grade invocation not consumed"
    current["registered"]+=1;joined=True;_note(stand,owner,place,current,"ran-coalesced")
   else:
    assert not current or current["delivered"]==current["registered"],"Previous grade invocation delivery not consumed"
    current={"label":label,"phase":"grading","registered":1,"delivered":0,"ready":threading.Event(),"consumed":threading.Event(),"started":time.monotonic(),"error":None}
    state["current"]=current;joined=False
  else:
   if not current or current["delivered"]==current["registered"]:return original(path,body)
   assert current["label"]==label,"Missing exact /ran binding"
   assert body.get("feed") and body["feed"][0].get("value") is True
   assert current["phase"] in ("ready","consuming","consumed"),"Missing exact /ran binding"
   joined=current["phase"]!="ready"
   if not joined:current["phase"]="consuming"
 if path=="/ran":
  if joined:
   timeout=stand.tasks[owner["taskId"]]["verifierSeconds"]+30
   assert current["ready"].wait(max(0.001,timeout-(time.monotonic()-current["started"]))),"Original grader delivery deadline"
   if current["error"] is not None:raise RuntimeError("Original grade invocation failed: "+current["error"])
   assert current.get("invocationId") and current["ranValue"]=={"value":True},"Original /ran delivery missing"
   return copy.deepcopy(current["ranValue"])
  try:
   value=original(path,body);pending=owner["pendingGrade"]
   assert value=={"value":True} and pending is not None and pending["label"]==label
   assert pending["record"]["policyReward"] in (0,1)
   with state["lock"]:
    current.update(phase="ready",invocationId=pending["record"]["invocationId"],ranValue=copy.deepcopy(value),policyReward=pending["record"]["policyReward"])
   return value
  except BaseException as error:
   with state["lock"]:current.update(phase="fault",error=type(error).__name__+": "+str(error))
   raise
  finally:current["ready"].set()
 if joined:
  timeout=stand.tasks[owner["taskId"]]["verifierSeconds"]+30
  assert current["consumed"].wait(max(0.001,timeout-(time.monotonic()-current["started"]))),"Original passed delivery deadline"
  with state["lock"]:
   if current["error"] is not None:raise RuntimeError("Original passed invocation failed: "+current["error"])
   assert current["phase"]=="consumed" and current["delivered"]<current["registered"],"Missing exact /ran binding"
   current["delivered"]+=1;_note(stand,owner,place,current,"passed-coalesced-delivered")
   return copy.deepcopy(current["passedValue"])
 try:
  value=original(path,body)
  assert owner["pendingGrade"] is None and isinstance(value,dict) and value.get("value") is bool(current["policyReward"])
  with state["lock"]:
   current.update(phase="consumed",delivered=1,passedValue=copy.deepcopy(value));_note(stand,owner,place,current,"grade-original-consumed-once")
  return value
 except BaseException as error:
  with state["lock"]:current.update(phase="fault",error=type(error).__name__+": "+str(error))
  raise
 finally:current["consumed"].set()
