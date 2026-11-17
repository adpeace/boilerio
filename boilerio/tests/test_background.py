from queue import Full
from threading import Event

import pytest

from boilerio.background import WorkerPool


def test_full_pool_rejects_new_keys_but_replaces_queued_jobs():
    worker = WorkerPool(workers=1, max_pending=1)
    started, release = Event(), Event()
    sent = []
    try:
        worker.submit('blocker', lambda: (started.set(), release.wait(2)))
        assert started.wait(0.5)
        worker.submit('reading', lambda: sent.append('old'))
        with pytest.raises(Full):
            worker.submit('other', lambda: sent.append('rejected'))
        worker.submit('reading', lambda: sent.append('latest'))
        release.set()
        assert worker.wait_idle(2)
        assert sent == ['latest']
    finally:
        release.set()
        worker.close()
        assert worker.wait_idle(2)


def test_closed_pool_rejects_submission():
    worker = WorkerPool()
    worker.close()
    with pytest.raises(RuntimeError):
        worker.submit('job', lambda: None)
