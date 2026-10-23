import { officialOpenRouterFault } from '../repair-2026-10-10/full-f/shared/digitalocean-provider.ts';

// A completed, billed generation can spend the entire output budget on reasoning.
// Its absent answer is a real failed sample, not an interface retry opportunity.
export function recoverEmptyLengthCompletion(receipt: any, response: any, maxTokens = 16384) {
  const choice = response?.choices?.[0], content = choice?.message?.content;
  const providerFault = officialOpenRouterFault(response);
  if (receipt?.httpStatus !== 200 || response?.error || choice?.error ||
      providerFault && providerFault !== 'MissingOrInvalidOpenRouterUsdCost' ||
      ![undefined, null, 'InvalidProviderCompletion', 'MissingOrInvalidOpenRouterUsdCost'].includes(receipt?.fault) ||
      choice?.finish_reason !== 'length' || response?.usage?.completion_tokens !== maxTokens ||
      content !== null && content !== undefined && content !== '') return undefined;
  return { answer: '', receipt, finishReason: 'length', requestSha256: receipt.requestSha256,
    responseClassification: 'token_budget_exhausted_without_answer',
    countsAsGeneratedSample: true, originalReceiptPreserved: true };
}
