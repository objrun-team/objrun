"""Staged literal uvx requirements review; never execute a vendor shell script.

Environment Dockerfile pins must not be merged into an isolated uvx verifier.
Unsupported dynamic requirements fail closed and require a separate review.
This source review does not certify an image, collection, or readiness.
"""
import re
import shlex

LITERAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:==[A-Za-z0-9_.+!-]+)?\Z')


def uvx_verifier_requirements(script):
    folded = script.replace('\\\n', ' ').replace('\\\r\n', ' ')
    invocations = []
    for line in folded.splitlines():
        if not re.match(r'^\s*uvx\s', line):
            continue
        tokens = shlex.split(line, comments=True)
        requirements = {}
        i = 1
        while i < len(tokens) and tokens[i].startswith('--'):
            if tokens[i] != '--with' or i + 1 >= len(tokens):
                raise ValueError('unreviewed_uvx_option')
            spec = tokens[i + 1]
            if not LITERAL.fullmatch(spec):
                raise ValueError('literal_verifier_requirement_required')
            key = re.sub(r'[-_.]+', '-', spec.split('==')[0]).lower()
            if key in requirements and requirements[key] != spec:
                raise ValueError('conflicting_verifier_requirement')
            requirements[key] = spec
            i += 2
        if i == len(tokens):
            raise ValueError('verifier_command_required')
        # The primary pytest invocation alone defines its environment. Later
        # optional score-generation invocations are retained, never unioned.
        invocations.append({'command': tokens[i], 'requirements': list(requirements.values())})
    primary = [item for item in invocations if item['command'] == 'pytest']
    if len(primary) != 1:
        raise ValueError('unique_literal_uvx_pytest_invocation_required')
    return {'primaryRequirements': primary[0]['requirements'], 'invocations': invocations,
            'candidateEnvironmentRequirementsMerged': False, 'sourceOnly': True,
            'actualPrivateBuildRequired': True, 'readinessCertified': False}
