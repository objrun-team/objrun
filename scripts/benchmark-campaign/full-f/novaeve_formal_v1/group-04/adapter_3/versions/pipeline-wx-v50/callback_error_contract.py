"""Pure classification of already-closed public candidate execution; no native calls."""
def candidate_failure(receipt):
 return bool(receipt.get('closeObserved') and not receipt.get('timedOut') and not receipt.get('overflow') and not receipt.get('captureFaults') and type(receipt.get('exitCode')) is int and receipt['exitCode']!=0)
