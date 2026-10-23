"""Observe persistent binary Popen pipes without changing the caller's IO loop.

The original owner still sends, reads, enforces limits, waits, kills and closes.
Call finish_interactive only after that owner's existing cleanup and joins.
"""
import datetime
import json
import pathlib
import threading
import time
from native_process import pin
from observed_owned_spawn import spawn_owned


class _ObservedPipe:
    def __init__(self, original, path, sink):
        self._original = original
        self._path = pathlib.Path(path)
        self._sink = sink
        self._lock = threading.Lock()
        self.bytes_observed = 0
        self.faults = []

    def _read(self, method, *args):
        value = getattr(self._original, method)(*args)
        if value:
            assert isinstance(value, bytes), 'interactive_binary_pipe_required'
            with self._lock:
                self.bytes_observed += len(value)
                try:
                    assert self._sink.write(value) == len(value)
                    self._sink.flush()
                except BaseException as error:
                    self.faults.append({'type': type(error).__name__, 'message': str(error)})
                    raise
        return value

    def read(self, *args):
        return self._read('read', *args)

    def readline(self, *args):
        return self._read('readline', *args)

    def __getattr__(self, name):
        return getattr(self._original, name)

    def evidence(self):
        with self._lock:
            if not self._sink.closed:
                self._sink.flush()
                self._sink.close()
            actual = pin(self._path)
            return dict(pin=actual, bytesObserved=self.bytes_observed,
                        originalPipeClosed=self._original.closed,
                        captureFaults=self.faults.copy())


def spawn_interactive(prefix, argv, **kwargs):
    prefix = pathlib.Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    assert not kwargs.get('text') and not kwargs.get('encoding'), 'binary_original_io_required'
    record = {}
    sinks = {}
    try:
        for key in ('stdout', 'stderr'):
            sinks[key] = pathlib.Path(str(prefix) + '.' + key).open('xb')
        child = spawn_owned(record, prefix, argv, **kwargs)
    except BaseException:
        for sink in sinks.values():
            sink.close()
        raise
    assert child.stdout is not None and child.stderr is not None
    child.stdout = _ObservedPipe(child.stdout, str(prefix) + '.stdout', sinks['stdout'])
    child.stderr = _ObservedPipe(child.stderr, str(prefix) + '.stderr', sinks['stderr'])
    child._bench_interactive = (prefix, record, time.monotonic())
    return child


def finish_interactive(child, reader_threads):
    prefix, record, started = child._bench_interactive
    readers_closed = not any(thread.is_alive() for thread in reader_threads)
    # Hash only after the original readers have stopped; never race a reader.
    assert readers_closed, 'original_interactive_readers_still_alive'
    streams = {key: getattr(child, key).evidence() for key in ('stdout', 'stderr')}
    record.update(finishedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  elapsedSeconds=time.monotonic() - started, exitCode=child.poll(),
                  closeObserved=child.poll() is not None, pipeReadersClosed=readers_closed,
                  stdinClosed=child.stdin is None or child.stdin.closed, streams=streams)
    complete = (record['closeObserved'] and record['stdinClosed'] and
                bool(record.get('incarnation')) and all(
                    s['originalPipeClosed'] and not s['captureFaults'] and
                    s['pin']['bytes'] == s['bytesObserved'] for s in streams.values()))
    record['complete'] = complete
    path = pathlib.Path(str(prefix) + '.closed.json')
    with path.open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    assert complete, 'original_interactive_closure_unproven'
    return pin(path)
