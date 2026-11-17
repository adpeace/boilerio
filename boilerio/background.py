"""Worker threads for bounded job queues with per-key coalescing."""

from collections import OrderedDict
from collections.abc import Callable, Hashable
import logging
from queue import Full
from threading import Condition, Thread
from typing import Protocol


logger = logging.getLogger(__name__)


class JobSubmitter(Protocol):
    """An object that accepts keyed jobs for execution."""

    def submit(self, key: Hashable, job: Callable[[], None]) -> None: ...


class WorkerPool:
    """A bounded pool of worker threads that runs one job per key at a time."""

    def __init__(self, workers=2, max_pending=256, name='http'):
        self._condition = Condition()
        self._pending = OrderedDict()
        self._running = set()
        self._closed = False
        self._max_pending = max_pending
        # Daemon threads let the process exit even if a remote peer is stuck.
        for index in range(workers):
            Thread(target=self._run, name=f'{name}-{index}', daemon=True).start()

    def submit(self, key: Hashable, job: Callable[[], None]) -> None:
        """Queue a job, replacing any queued job with the same key.

        Raise queue.Full if the queue has no room for a new key, or RuntimeError
        if the pool has been closed.
        """
        # Callers retain pending state when the queue cannot accept their job.
        with self._condition:
            if self._closed:
                raise RuntimeError('Worker pool is closed')
            if key not in self._pending and len(self._pending) >= self._max_pending:
                raise Full('Background work queue is full')
            self._pending[key] = job
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or any(
                    key not in self._running for key in self._pending))
                if self._closed:
                    return
                key = next(key for key in self._pending if key not in self._running)
                job = self._pending.pop(key)
                self._running.add(key)
            try:
                job()
            except Exception:
                logger.exception('Unexpected error in background work')
            finally:
                with self._condition:
                    self._running.remove(key)
                    self._condition.notify_all()

    def wait_idle(self, timeout):
        """Wait up to timeout seconds for all jobs to finish; return whether idle."""
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending and not self._running, timeout)

    def close(self):
        """Stop accepting jobs and discard queued work without waiting for running jobs."""
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
