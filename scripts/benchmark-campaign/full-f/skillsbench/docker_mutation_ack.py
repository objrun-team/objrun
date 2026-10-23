"""Require actual container removal acknowledgement, even with CLI exit zero."""
import re


def require(args, stdout):
    if not args or args[0] != 'rm': return
    expected = [item for item in args[1:] if not item.startswith('-')]
    if not expected or any(not re.fullmatch(r'[0-9a-f]{64}', item) for item in expected):
        raise ValueError('exact_owned_container_removal_required')
    try: acknowledged = stdout.decode('ascii').strip().splitlines()
    except (AttributeError, UnicodeError) as error:
        raise ValueError('container_removal_acknowledgement_missing') from error
    if acknowledged != expected:
        raise ValueError('container_removal_acknowledgement_missing')
