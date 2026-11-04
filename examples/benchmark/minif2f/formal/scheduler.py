"""Event-driven HTTP attempts, independent Lean futures and delayed retry queue."""
from __future__ import annotations
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import heapq
import itertools
import json
import os
from pathlib import Path
import time
from lean_worker import digest, save
from sequence import messages, check_messages
from transport import BudgetStop

class Scheduler:
    def __init__(self, root, cfg, catalog, transport, grader, frozen=lambda: None):
        self.root, self.cfg, self.transport, self.grader = root, cfg, transport, grader
        self.frozen = frozen
        self.fresh = deque((q, cfg['arms'][(i+j) % 2]) for i,q in enumerate(catalog) for j in range(2))
        self.ready = []; self.serial = itertools.count(); self.network = {}; self.grades = {}
        self.states = {}; self.results = {}; self.stage = 'running'
        self.pool = ThreadPoolExecutor(max_workers=cfg['modelConcurrency'], thread_name_prefix='model-http')
        self.last_status = 0

    def enqueue(self, state, index, retry=0, delay=0):
        heapq.heappush(self.ready, (time.monotonic()+delay, next(self.serial), state['group'], index, retry))

    def begin(self, task, arm):
        self.frozen()
        group = arm + '/' + task['name']; start = time.time()
        directory = self.root / 'outputs/tasks' / group
        directory.mkdir(parents=True, exist_ok=False)
        state = {'group': group, 'task': task, 'arm': arm, 'history': [], 'start': start,
                 'deadline': start+self.cfg['perTaskSeconds'], 'directory': directory, 'terminal': False}
        save(directory / 'started.json', {'atEpoch': start, 'deadlineEpoch': state['deadline'],
                                        'arm': arm, 'id': task['id']})
        self.states[group] = state
        return state

    def finish(self, state, reason, error=None):
        if state['terminal']: return
        history = state['history']
        grade = history[-1]['grade'] if history else {'valid': True, 'passed': False, 'outcome': 'budget_no_candidate'}
        if error is not None: grade = {'valid': False, 'passed': False, 'outcome': 'infrastructure_exception'}
        result = {'arm': state['arm'], 'id': state['task']['id'], 'name': state['task']['name'],
            'promptSha256': state['task']['promptSha256'], 'startedAtEpoch': state['start'],
            'completedAtEpoch': time.time(), 'seconds': time.time()-state['start'],
            'sampleCount': len(history), 'answer': history[-1]['answer'] if history else '',
            'candidateSha256': digest(history[-1]['answer'] if history else ''),
            'grade': grade, 'stoppingReason': reason}
        if error is not None: result['error'] = str(error)
        # Per-group counters are recomputed at final reporting if a late request settles.
        result.update(self.transport.accounting(state['group']))
        state['terminal'] = True; self.results[state['group']] = result
        (state['directory'] / 'final-answer.txt').write_text(result['answer'])
        save(self.root / 'outputs/results' / state['arm'] / (state['task']['name']+'.json'), result)
        self.event('task_terminal', state, reason=reason, valid=grade['valid'], passed=grade['passed'])

    def event(self, kind, state, **details):
        with (self.root / 'outputs/scheduler-events.jsonl').open('a') as stream:
            stream.write(json.dumps({'event': kind, 'atEpoch': time.time(), 'group': state['group'], **details})+'\n')

    def status(self, force=False):
        if not force and time.monotonic()-self.last_status < 15: return
        self.last_status = time.monotonic(); self.frozen()
        records = list(self.results.values())
        save(self.root / 'outputs/status.json', {'runId': self.cfg['runId'], 'stage': self.stage,
            'pid': os.getpid(), 'updatedAtEpoch': time.time(), 'planned': self.cfg['expectedRecords'],
            'completed': len(records), 'unstarted': len(self.fresh),
            'active': [{'arm':s['arm'],'id':s['task']['id']} for s in self.states.values() if not s['terminal']],
            'httpFutures': len(self.network), 'pendingGrades': len(self.grades), 'delayedOrReadyAttempts': len(self.ready),
            'graderActive': self.grader.active, 'graderPeak': self.grader.peak,
            'arms': {a: {'recorded': sum(r['arm']==a for r in records),
                'valid': sum(r['arm']==a and r['grade']['valid'] for r in records),
                'passed': sum(r['arm']==a and r['grade']['valid'] and r['grade']['passed'] for r in records)}
                for a in self.cfg['arms']}, **self.transport.accounting(), 'fatal': self.transport.fatal})

    def dispatched(self, future, state, index, retry):
        try: answer, receipt, call = future.result()
        except BudgetStop as exc:
            self.finish(state, str(exc)); return
        except Exception as exc:
            self.finish(state, 'infrastructure_exception', exc); return
        if state['terminal']:
            save(state['directory'] / ('late-http-%02d-%02d.json' % (index,retry)),
                 {'answer':answer,'receipt':receipt,'callDirectory':call,'excludedFromScore':True})
            return
        if not receipt['success']:
            if receipt['retryable'] and retry+1 < self.cfg['maxTransportAttempts'] and not self.transport.fatal:
                delay = self.cfg['transportBackoffSeconds']*(retry+1)
                self.enqueue(state,index,retry+1,delay)
                self.event('retry_scheduled',state,index=index,retry=retry+1,delaySeconds=delay,callDirectory=call)
            else: self.finish(state,'infrastructure_exception',receipt['fault'])
            return
        (state['directory'] / ('candidate-%02d.txt' % index)).write_text(answer)
        if time.time() >= state['deadline']:
            save(state['directory'] / ('late-http-%02d-%02d.json' % (index,retry)),
                 {'answer':answer,'receipt':receipt,'callDirectory':call,'excludedFromScore':True})
            self.finish(state,'infrastructure_exception','DeliveredAfterTaskDeadline'); return
        future = self.grader.accept(state['task'],answer)
        self.grades[future] = (state,index,answer,receipt,call)

    def graded(self, future, state, index, answer, receipt, call):
        if state['terminal']:
            try: value = future.result()
            except Exception as exc: value = {'valid':False,'passed':False,'error':str(exc)}
            save(state['directory'] / ('late-grade-%02d.json' % index),
                 {'grade':value,'candidateSha256':digest(answer),'callDirectory':call,'excludedFromScore':True})
            return
        try: grade = future.result()
        except Exception as exc:
            grade = {'valid':False,'passed':False,'candidateSha256':digest(answer),'outcome':'grader_future_error','error':str(exc)}
        if time.time() >= state['deadline']:
            save(state['directory'] / ('late-grade-%02d.json' % index),
                 {'grade':grade,'candidateSha256':digest(answer),'callDirectory':call,'excludedFromScore':True})
            self.finish(state,'infrastructure_exception','GradingExceededTaskDeadline'); return
        assert index == len(state['history'])
        sample = {'index': index, 'answer': answer, 'candidateSha256': digest(answer), 'grade': grade,
                  'receipt': receipt, 'callDirectory': call, 'finishedAtEpoch': time.time()}
        state['history'].append(sample)
        save(state['directory'] / 'samples.json',state['history'])
        if not grade['valid']: self.finish(state,'infrastructure_exception','PrivateGraderInfrastructureError')
        elif grade['passed']: self.finish(state,'first_correct')
        elif len(state['history']) == self.cfg['maxAttempts']: self.finish(state,'five_attempt_ceiling')
        else: self.enqueue(state,index+1)

    def run(self):
        try:
            while self.fresh or self.ready or self.network or self.grades:
                # Completion events drive refill immediately; no heartbeat drives scheduling.
                for future in [f for f in self.network if f.done()]:
                    state,index,retry = self.network.pop(future)
                    self.dispatched(future,state,index,retry)
                for future in [f for f in self.grades if f.done()]:
                    self.graded(future,*self.grades.pop(future))
                for state in self.states.values():
                    if not state['terminal'] and time.time() >= state['deadline']:
                        busy = any(x[0] is state for x in self.network.values()) or any(x[0] is state for x in self.grades.values())
                        self.finish(state,'infrastructure_exception' if busy else 'task_time_cap',
                                    'TaskDeadlineWithUnresolvedWork' if busy else None)
                if self.transport.fatal:
                    while self.fresh:
                        task,arm = self.fresh.popleft()
                        self.finish(self.begin(task,arm),'infrastructure_exception',self.transport.fatal)
                    for state in self.states.values():
                        if not state['terminal']: self.finish(state,'infrastructure_exception',self.transport.fatal)
                    self.ready.clear()
                while len(self.network) < self.cfg['modelConcurrency']:
                    job = None
                    while self.ready and self.ready[0][0] <= time.monotonic():
                        _,_,group,index,retry = heapq.heappop(self.ready)
                        state = self.states[group]
                        if not state['terminal']: job = (state,index,retry); break
                    if job is None and self.fresh:
                        task,arm = self.fresh.popleft(); job = (self.begin(task,arm),0,0)
                    if job is None: break
                    state,index,retry = job
                    if time.time() >= state['deadline']:
                        self.finish(state,'task_time_cap'); continue
                    sent = messages(self.cfg['systemPrompt'],state['task']['prompt'],state['arm'],state['history'])
                    check_messages(sent,self.cfg['systemPrompt'],state['task'],state['arm'],state['history'])
                    self.event('http_submitted',state,index=index,retry=retry)
                    future = self.pool.submit(self.transport.dispatch_once,state['group'],index,retry,sent,state['deadline'])
                    self.network[future] = (state,index,retry)
                self.status()
                pending = list(self.network)+list(self.grades)
                timeout = min(1.,max(.001,self.ready[0][0]-time.monotonic())) if self.ready else 1.
                if pending: wait(pending,timeout=timeout,return_when=FIRST_COMPLETED)
                elif self.ready: time.sleep(timeout)
            self.stage = 'complete' if all(r['grade']['valid'] for r in self.results.values()) else 'complete_with_exceptions'
        finally:
            self.pool.shutdown(wait=True)
            self.grader.close()
            self.status(force=True)
        assert len(self.results)==self.cfg['expectedRecords']
        return list(self.results.values())
