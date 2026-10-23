// Inactive proposal: preserve all messages/reasoning; request a new tool turn.
// No schema, tool choice, effort, budget, grader or provider changes.
export function submitNextTurn(messages, previous, mustCall) {
  if (mustCall !== 'submit' || previous.finishReason !== 'length' ||
      previous.toolCalls.length || previous.text || !previous.reasoningText) return messages;
  return [...messages, { role: 'user', content: 'The preceding response was truncated without a submit tool call. Continue from the preserved reasoning and call the available submit tool. A text-only response is not a submission.' }];
}
