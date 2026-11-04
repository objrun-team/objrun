"""Pinned OpenRouter route, finite transport chain, raw receipts and shared reservations."""
from __future__ import annotations
import hashlib
import http.client
import json
import math
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from lean_worker import digest, save

class BudgetStop(Exception): pass

class Transport:
    def __init__(self, root, cfg, key):
        self.root, self.cfg, self.key = root, cfg, key
        self.lock = threading.Lock(); self.held = 0.; self.group_held = {}; self.remaining = float('inf')
        self.pace_lock = threading.Lock(); self.next_dispatch = 0.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': cfg['proxy'], 'https': cfg['proxy']}))
        self.fatal = None

    def get(self, path, authenticated=True):
        headers = {'connection': 'close'}
        if authenticated: headers['authorization'] = 'Bearer ' + self.key
        request = urllib.request.Request('https://openrouter.ai/api/v1/' + path, headers=headers)
        with self.opener.open(request, timeout=25) as response: return json.load(response)

    def preflight(self):
        endpoint = self.get('models/' + self.cfg['model'] + '/endpoints', False)
        match = next((e for e in endpoint['data']['endpoints'] if e.get('tag') == self.cfg['providerTag']), None)
        if match is None: raise RuntimeError('PinnedEndpointUnavailable')
        for param in ['reasoning', 'temperature', 'max_tokens']:
            if param not in match['supported_parameters']: raise RuntimeError('UnsupportedParameter:' + param)
        prices = [match['pricing'], *match['pricing'].get('overrides', [])]
        for price in prices:
            if float(price.get('prompt', match['pricing']['prompt'])) * 1e6 > self.cfg['inputUsdPerMillionCeiling'] + 1e-9: raise RuntimeError('InputTariffChanged')
            if float(price.get('completion', match['pricing']['completion'])) * 1e6 > self.cfg['outputUsdPerMillionCeiling'] + 1e-9: raise RuntimeError('OutputTariffChanged')
        save(self.root / 'outputs/provider-observation.json', endpoint)
        credits, key_state = self.get('credits')['data'], self.get('key')['data']
        self.remaining = min(credits['total_credits'] - credits['total_usage'], key_state.get('limit_remaining') if key_state.get('limit_remaining') is not None else float('inf'))
        if not math.isfinite(self.remaining) or self.remaining < 0: raise RuntimeError('AccountUnavailable')
        save(self.root / 'outputs/balance-before.json', {'remainingUsd': self.remaining, 'atUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        return {'providerTag': match['tag'], 'pricing': match['pricing'], 'remainingUsd': self.remaining}

    def accounting(self, group=None):
        path = self.root / 'outputs/calls'
        if group: path = path / group
        receipts = [json.loads(p.read_text()) for p in path.rglob('receipt.json')] if path.exists() else []
        unresolved = [json.loads(p.read_text()) for p in path.rglob('dispatch.json') if not (p.parent / 'receipt.json').exists()] if path.exists() else []
        return {'modelRequests': len(receipts) + len(unresolved), 'actualCostUsd': sum(r['actualCostUsd'] or 0 for r in receipts),
                'unknownCostCount': sum(r['unknownCost'] for r in receipts) + len(unresolved),
                'budgetChargedUsd': sum(r['actualCostUsd'] if r['actualCostUsd'] is not None else r['reservationUsd'] for r in receipts) + sum(r['reservationUsd'] for r in unresolved),
                'unresolvedDispatches': len(unresolved)}

    def generate(self, group, index, messages, deadline):
        cfg = self.cfg
        wire = {'model': cfg['model'], 'stream': False, 'messages': messages, 'temperature': cfg['temperature'], 'max_tokens': cfg['maxTokens'],
                'reasoning': {'enabled': True, 'effort': cfg['reasoningEffort'], 'exclude': False},
                'provider': {'only': [cfg['providerTag']], 'allow_fallbacks': False, 'require_parameters': True,
                             'max_price': {'prompt': cfg['inputUsdPerMillionCeiling'], 'completion': cfg['outputUsdPerMillionCeiling']}}}
        raw = json.dumps(wire, ensure_ascii=False).encode()
        reservation = ((len(raw) + 2048) * cfg['inputUsdPerMillionCeiling'] + cfg['maxTokens'] * cfg['outputUsdPerMillionCeiling']) / 1e6
        offset = cfg.get('transportRetryOffset', 0)
        for relative_retry in range(cfg['maxTransportAttempts']):
            retry = offset + relative_retry
            directory = self.root / 'outputs/calls' / group / ('attempt-%02d' % index) / ('transport-%02d' % retry)
            rp = directory / 'receipt.json'
            if rp.exists():
                receipt = json.loads(rp.read_text())
                if receipt['success']:
                    response = json.loads((directory / 'response.json').read_text())
                    return response['choices'][0]['message'].get('content') or '', receipt, str(directory.relative_to(self.root))
                if not receipt.get('retryable', False): raise RuntimeError('PreviousNonretryableTransportFault:' + str(receipt.get('fault')))
                continue
            if (directory / 'dispatch.json').exists(): raise RuntimeError('UnresolvedDispatchRequiresReconciliation')
            if time.time() >= deadline: raise BudgetStop('task_time_cap')
            with self.pace_lock:
                delay = max(0., self.next_dispatch - time.monotonic())
                if time.time() + delay >= deadline: raise BudgetStop('task_time_cap')
                if delay: time.sleep(delay)
                self.next_dispatch = time.monotonic() + cfg.get('requestSpacingSeconds', 0.)
            with self.lock:
                if self.fatal: raise RuntimeError(self.fatal)
                current = self.accounting()
                local = self.accounting(group)
                # Existing dispatches already reserve their full amount in accounting().
                if local['budgetChargedUsd'] + reservation > cfg['perTaskDollarCap'] + 1e-12: raise BudgetStop('task_dollar_cap')
                if current['budgetChargedUsd'] + reservation > cfg['batchDollarCap'] + 1e-12: raise BudgetStop('batch_dollar_cap')
                if current['budgetChargedUsd'] + reservation > self.remaining: raise BudgetStop('account_balance')
                self.held += reservation; self.group_held[group] = self.group_held.get(group, 0.) + reservation
                directory.mkdir(parents=True, exist_ok=False)
                (directory / 'request.json').write_bytes(raw)
                save(directory / 'dispatch.json', {'atEpoch': time.time(), 'requestSha256': digest(raw), 'reservationUsd': reservation, 'group': group, 'index': index, 'transportAttempt': retry})
            status, response, fault = 0, {}, None
            started = time.time()
            try:
                req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=raw,
                      headers={'authorization': 'Bearer ' + self.key, 'content-type': 'application/json', 'connection': 'close', 'X-OpenRouter-Title': cfg['runId']})
                try: result = self.opener.open(req, timeout=min(600, max(1, deadline - time.time())))
                except urllib.error.HTTPError as exc: result = exc
                with result:
                    status = result.status
                    save(directory / 'response-headers.json', {k: result.headers.get(k) for k in ['content-type', 'date', 'x-generation-id', 'x-request-id']})
                    body = b''
                    with (directory / 'response.raw.txt').open('wb') as output:
                        try:
                            while chunk := result.read(65536): body += chunk; output.write(chunk); output.flush()
                        except http.client.IncompleteRead as exc:
                            body += exc.partial; output.write(exc.partial); raise
                    response = json.loads(body)
                    save(directory / 'response.json', response)
                if status != 200: fault = 'ProviderHTTP' + str(status)
                elif response.get('provider') != cfg['provider']: fault = 'UnexpectedProvider'
                elif response.get('model') != cfg['model']: fault = 'UnexpectedModel'
                elif not response.get('id') or not response.get('choices'): fault = 'IncompleteProviderResponse'
                elif not isinstance(response['choices'][0].get('message', {}).get('content', ''), (str, type(None))): fault = 'InvalidContentShape'
                elif response['choices'][0].get('finish_reason') == 'error': fault = 'ProviderFinishError'
            except Exception as exc: fault = type(exc).__name__ + ':' + str(exc)
            usage = response.get('usage') or {}
            cost = usage.get('cost')
            if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0: cost = None
            rejected = status in [400, 401, 402, 403, 404, 429] and not response.get('id') and not usage
            if rejected: cost = 0.
            receipt = {'success': status == 200 and fault is None, 'httpStatus': status, 'fault': fault,
                       'generationId': response.get('id'), 'model': response.get('model'), 'provider': response.get('provider'),
                       'usage': usage, 'actualCostUsd': cost, 'unknownCost': cost is None, 'reservationUsd': reservation,
                       'requestSha256': digest(raw), 'finishReason': (response.get('choices') or [{}])[0].get('finish_reason'),
                       'retryable': status in [0, 429] or status >= 500,
                       'seconds': time.time() - started, 'completedAtEpoch': time.time()}
            with self.lock:
                save(rp, receipt)
                self.held -= reservation; self.group_held[group] -= reservation
                if status in [401, 402, 403] or fault in ['UnexpectedModel', 'UnexpectedProvider']: self.fatal = str(fault)
            if receipt['success']: return response['choices'][0]['message'].get('content') or '', receipt, str(directory.relative_to(self.root))
            if self.fatal: raise RuntimeError(self.fatal)
            retryable = status in [0, 429] or status >= 500
            if not retryable or relative_retry == cfg['maxTransportAttempts'] - 1: raise RuntimeError('TransportChainFailed:' + str(fault))
            time.sleep(min(cfg.get('transportBackoffSeconds', 2.) * (relative_retry + 1), max(0, deadline - time.time())))
        raise RuntimeError('TransportChainExhausted')
