"""The only code allowed to turn a private grade into model-visible feedback."""
def messages(system, prompt, arm, history):
    if arm not in ('independent', 'binary'): raise ValueError('UnknownArm')
    output = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
    if arm == 'binary':
        for sample in history:
            if not sample['grade']['valid']: raise ValueError('InvalidGradeMustNotBecomeFeedback')
            output.extend([{'role': 'assistant', 'content': sample['answer']},
                           {'role': 'user', 'content': 'passed' if sample['grade']['passed'] else 'failed'}])
    return output

def check_messages(actual, system, task, arm, history):
    expected = messages(system, task['prompt'], arm, history)
    if actual != expected: raise ValueError('InformationIsolationViolation')
    if arm == 'independent' and len(actual) != 2: raise ValueError('IndependentHistoryLeak')
    if arm == 'binary' and any(m['content'] not in ('passed', 'failed') for m in actual[3::2]):
        raise ValueError('NonBinaryFeedback')
    return True
