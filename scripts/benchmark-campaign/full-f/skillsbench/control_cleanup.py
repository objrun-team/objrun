"""Retain primary control failure and unknown cleanup state on Docker faults."""
def capture(result, stand):
    if stand is None:
        return None
    try:
        result['solverClosure'] = stand.stop()
        return None
    except Exception as error:
        result['verified'] = False
        result['candidateEnvironmentParityVerified'] = False
        result['cleanupFailure'] = {'type': type(error).__name__, 'detail': str(error)}
        current = getattr(stand, 'current', None)
        result['solverClosure'] = {'ownedContainersRemaining': None, 'cleanupComplete': False,
            'attemptedOwnedContainerId': current.get('cid') if isinstance(current, dict) else None}
        # None means inventory is unknown; zero would assert successful cleanup.
        result['ownedResourcesRemaining'] = None
        return error
