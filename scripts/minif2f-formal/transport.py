"""One HTTP attempt per lease; all arms share one bounded pool and cash ledger."""
from __future__ import annotations
import http.client
import json
import math
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from lean_worker import digest, save
from pilot_transport import Transport as PilotTransport, BudgetStop

class Transport(PilotTransport):
    def __init__(self, root, cfg, key, control_endpoint=None):
        super().__init__(root, cfg, key)
        self.lock = threading.RLock()
        self.entries = {}
        self.active = self.peak = 0
        self.slots = threading.BoundedSemaphore(cfg['modelConcurrency'])
        self.endpoint = 'https://openrouter.ai/api/v1/chat/completions'
        if control_endpoint is not None:
            assert cfg.get('controlOnly') is True and control_endpoint.startswith('http://127.0.0.1:')
            self.endpoint = control_endpoint
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        assert not list((root / 'outputs/calls').rglob('dispatch.json')), 'ExistingCallsRequireReconciliation'

    def accounting(self, group=None):
        with self.lock:
            values = [v for v in self.entries.values() if group is None or v['group'] == group]
            return {'modelRequests': len(values),
                'actualCostUsd': sum(v.get('actualCostUsd') or 0 for v in values),
                'unknownCostCount': sum(v.get('actualCostUsd') is None for v in values),
                'budgetChargedUsd': sum(v['actualCostUsd'] if v.get('actualCostUsd') is not None else v['reservationUsd'] for v in values),
                'unresolvedDispatches': sum(not v['resolved'] for v in values),
                'actualModelActive': self.active, 'actualModelPeak': self.peak}

    def event(self, kind, call, **extra):
        # Called under the same lock as the active counter and ledger.
        value = {'event': kind, 'callDirectory': call, 'atEpoch': time.time(),
                 'monotonic': time.monotonic(), 'active': self.active, **extra}
        path = self.root / 'outputs/model-concurrency.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream: stream.write(json.dumps(value) + '\n')
        return value['atEpoch']

    def dispatch_once(self, group, index, retry, messages, deadline):
        cfg = self.cfg
        if time.time() >= deadline: raise BudgetStop('task_time_cap')
        assert 0 <= index < cfg['maxAttempts'] and 0 <= retry < cfg['maxTransportAttempts']
        wire = {'model': cfg['model'], 'stream': False, 'messages': messages,
            'temperature': cfg['temperature'], 'max_tokens': cfg['maxTokens'],
            'reasoning': {'enabled': True, 'effort': cfg['reasoningEffort'], 'exclude': False},
            'provider': {'only': [cfg['providerTag']], 'allow_fallbacks': False,
                'require_parameters': True, 'max_price': {'prompt': cfg['inputUsdPerMillionCeiling'],
                                                         'completion': cfg['outputUsdPerMillionCeiling']}}}
        raw = json.dumps(wire, ensure_ascii=False).encode()
        reserve = ((len(raw) + 2048) * cfg['inputUsdPerMillionCeiling'] +
                   cfg['maxTokens'] * cfg['outputUsdPerMillionCeiling']) / 1e6
        d = self.root / 'outputs/calls' / group / ('attempt-%02d' % index) / ('transport-%02d' % retry)
        call = str(d.relative_to(self.root))
        with self.lock:
            if self.fatal: raise RuntimeError(self.fatal)
            total, local = self.accounting(), self.accounting(group)
            if local['budgetChargedUsd'] + reserve > cfg['perTaskDollarCap'] + 1e-12: raise BudgetStop('task_dollar_cap')
            if total['budgetChargedUsd'] + reserve > cfg['batchDollarCap'] + 1e-12: raise BudgetStop('batch_dollar_cap')
            if total['budgetChargedUsd'] + reserve > self.remaining: raise BudgetStop('account_balance')
            d.mkdir(parents=True, exist_ok=False)
            (d / 'request.json').write_bytes(raw)
            save(d / 'dispatch.json', {'atEpoch': time.time(), 'requestSha256': digest(raw),
                'reservationUsd': reserve, 'group': group, 'index': index, 'transportAttempt': retry})
            self.entries[call] = {'group': group, 'reservationUsd': reserve, 'resolved': False}
        status, response, fault, network_start = 0, {}, None, None
        started = time.time()
        with self.slots:
            with self.lock:
                self.active += 1; self.peak = max(self.peak, self.active)
                assert self.active <= cfg['modelConcurrency']
                network_start = self.event('http_begin', call, group=group, index=index, retry=retry)
            try:
                if time.time() >= deadline: raise TimeoutError('TaskDeadlineBeforeHTTP')
                req = urllib.request.Request(self.endpoint, data=raw,
                    headers={'authorization': 'Bearer ' + self.key, 'content-type': 'application/json',
                             'connection': 'close', 'X-OpenRouter-Title': cfg['runId']})
                try: result = self.opener.open(req, timeout=min(600, max(1, deadline - time.time())))
                except urllib.error.HTTPError as exc: result = exc
                with result:
                    status = result.status
                    save(d / 'response-headers.json', {k: result.headers.get(k) for k in
                        ['content-type', 'date', 'x-generation-id', 'x-request-id']})
                    body = b''
                    with (d / 'response.raw.txt').open('wb') as output:
                        try:
                            while chunk := result.read(65536):
                                body += chunk; output.write(chunk); output.flush()
                                if time.time() >= deadline: raise TimeoutError('TaskDeadlineDuringHTTP')
                        except http.client.IncompleteRead as exc:
                            body += exc.partial; output.write(exc.partial); raise
                    response = json.loads(body); save(d / 'response.json', response)
                if status != 200: fault = 'ProviderHTTP' + str(status)
                elif response.get('provider') != cfg['provider']: fault = 'UnexpectedProvider'
                elif response.get('model') != cfg['model']: fault = 'UnexpectedModel'
                elif not response.get('id') or not response.get('choices'): fault = 'IncompleteProviderResponse'
                elif not isinstance(response['choices'][0].get('message', {}).get('content', ''), (str, type(None))):
                    fault = 'InvalidContentShape'
                elif response['choices'][0].get('finish_reason') == 'error': fault = 'ProviderFinishError'
            except Exception as exc: fault = type(exc).__name__ + ':' + str(exc)
            finally:
                with self.lock:
                    self.active -= 1
                    network_end = self.event('http_end', call, httpStatus=status)
        usage = response.get('usage') or {}
        cost = usage.get('cost')
        if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0: cost = None
        if status in [400, 401, 402, 403, 404, 429] and not response.get('id') and not usage: cost = 0.
        receipt = {'success': status == 200 and fault is None, 'httpStatus': status, 'fault': fault,
            'generationId': response.get('id'), 'model': response.get('model'), 'provider': response.get('provider'),
            'usage': usage, 'actualCostUsd': cost, 'unknownCost': cost is None, 'reservationUsd': reserve,
            'requestSha256': digest(raw), 'finishReason': (response.get('choices') or [{}])[0].get('finish_reason'),
            'retryable': status in [0, 429] or status >= 500, 'seconds': time.time() - started,
            'networkStartedAtEpoch': network_start, 'networkEndedAtEpoch': network_end,
            'completedAtEpoch': time.time()}
        with self.lock:
            save(d / 'receipt.json', receipt)
            self.entries[call].update(receipt, resolved=True)
            if status in [401, 402, 403] or fault in ['UnexpectedModel', 'UnexpectedProvider']:
                self.fatal = str(fault)
            if cost is not None and cost > reserve + 1e-9: self.fatal = 'CostExceededConservativeReservation'
        answer = (response.get('choices') or [{}])[0].get('message', {}).get('content') or ''
        return answer if receipt['success'] else '', receipt, call
