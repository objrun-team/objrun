/** Publish reviewed runtime JSON with the existing authority. Never launches a task. */
import { createPublicKey, sign, verify } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadManifest, verifyPin, pin, demand } from './manifest.ts';
import { wxJson } from './runtime.ts';
import type { Pin } from './types.ts';

export function authorizeBinding(reviewPin: Pin, privateKeyPath: string): Pin {
  verifyPin(reviewPin);
  const review = JSON.parse(readFileSync(reviewPin.path, 'utf8'));
  demand(review.protocol === 'bench-concrete-binding-review-v1' && review.rootReviewed === true, 'concrete_root_review_required');
  demand(review.inventoryReconciled === true && review.zeroModelChecksPassed === true, 'inventory_and_zero_model_gate_required');
  demand(Array.isArray(review.evidencePins) && review.evidencePins.length > 0, 'concrete_review_evidence_required');
  demand(Date.parse(review.expiresAtUtc) > Date.now(), 'concrete_review_expired');
  for (const p of [review.manifestPin, review.requestPin, review.draftPin, ...review.evidencePins]) verifyPin(p);
  const m = loadManifest(review.manifestPin.path), request = JSON.parse(readFileSync(review.requestPin.path, 'utf8'));
  demand(request.protocol === 'bench-root-signing-request-v1', 'binding_request_required');
  demand(JSON.stringify(request.draftPin) === JSON.stringify(review.draftPin), 'reviewed_draft_identity');
  const configured = m.adapterConfig.bindingSpec as any;
  demand(configured && request.authorityPin.sha256 === configured.authorityPin.sha256 && request.authorityPin.path === configured.authorityPin.path, 'original_authority_pin_required');
  verifyPin(request.authorityPin);
  const draft = JSON.parse(readFileSync(review.draftPin.path, 'utf8'));
  demand(draft.taskId === m.taskId && draft.bench === m.bench && draft.rootRuntimeBinding?.attemptId === draft.nonce, 'concrete_task_attempt_identity');
  demand(JSON.stringify(draft.rootRuntimeBinding.manifestPin) === JSON.stringify(review.manifestPin), 'concrete_manifest_identity');
  demand(draft.rootRuntimeBinding.bindings.ENTRY_ENVELOPE === request.signedEnvelopeDestination, 'signed_destination_identity');
  demand(!draft.blockReasons?.length && !existsSync(request.signedEnvelopeDestination), 'blocked_or_already_signed');
  const privateKey = readFileSync(resolve(privateKeyPath), 'utf8');
  const publicKey = createPublicKey(privateKey).export({ type: 'spki', format: 'pem' }).toString();
  demand(publicKey.trim() === readFileSync(request.authorityPin.path, 'utf8').trim(), 'private_key_not_original_authority');
  const entry = { ...draft, coordinatorReviewed: true, phase: 'ready' };
  const signature = sign(null, Buffer.from(JSON.stringify(entry)), privateKey).toString('base64');
  demand(verify(null, Buffer.from(JSON.stringify(entry)), publicKey, Buffer.from(signature, 'base64')), 'signature_self_verification_failed');
  verifyPin(reviewPin); verifyPin(review.draftPin); verifyPin(review.manifestPin);
  wxJson(request.signedEnvelopeDestination, { protocol: 'novaeve-root-signed-entry-v4', entry, signature });
  return pin(request.signedEnvelopeDestination);
}

if (import.meta.main) {
  demand(process.argv[2] === '--review-pin' && process.argv[3] && process.argv[4] === '--private-key' && process.argv[5], 'use_review_pin_json_and_existing_private_key');
  const result = authorizeBinding(JSON.parse(readFileSync(resolve(process.argv[3]), 'utf8')), process.argv[5]);
  console.log(JSON.stringify({ signedEnvelopePin: result, newModelNativeCalls: 0, secretsPrinted: false }));
}
