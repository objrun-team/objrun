"""Keep verifier failures separate from valid candidate rejections."""
import math

class GraderFault(Exception):
    pass

def require_result(result):
    if not isinstance(result, dict) or result.get('crashed'):
        raise GraderFault('Verifier failed')
    if 'reward' not in result:
        raise GraderFault('Missing reward')
    reward = result['reward']
    if type(reward) not in (int, float) or not math.isfinite(reward) or not 0 <= reward <= 1:
        raise GraderFault('Invalid reward')
    return result

def fault_payload(error):
    # Exception messages can include hidden test content or expected outputs.
    return {'valid': False, 'outcome': 'grader_error', 'errorType': type(error).__name__}

def can_cache_result(result):
    try:
        require_result(result)
        return True
    except GraderFault:
        return False


def require_valid_verdict(result):
    """A boolean candidate verdict is cacheable only after successful grading."""
    if not isinstance(result,dict) or type(result.get('valid')) is not bool or type(result.get('passed')) is not bool:
        raise GraderFault('Malformed boolean verdict')
    if not result['valid']:
        raise GraderFault('Grading environment failed')
    return result
