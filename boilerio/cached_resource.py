"""HTTP resource caches, persistent backups, and startup refreshes."""

from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Mapping
from concurrent.futures import Future, wait
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
from pathlib import Path
from queue import Full
from tempfile import NamedTemporaryFile
import time
from typing import Any, Generic, TypeAlias, TypeVar

import requests
from requests.auth import AuthBase

from .background import JobSubmitter, WorkerPool


logger = logging.getLogger(__name__)

T = TypeVar('T')
K = TypeVar('K', bound=Hashable)
CachePath: TypeAlias = str | os.PathLike[str]
RequestAuth: TypeAlias = AuthBase | tuple[str, str]
QueryParams: TypeAlias = Mapping[str, str | int | float | None]


@dataclass(frozen=True)
class FetchRequest(Generic[T]):
    """An HTTP GET request and the parser for its response text."""

    url: str
    parser: Callable[[str], T]
    auth: RequestAuth | None = None
    params: QueryParams | None = None


@dataclass(frozen=True)
class FetchResult(Generic[T]):
    """A parsed HTTP response, its original text, and its monotonic completion time."""

    value: T | None
    text: str | None
    completed_at: float

    @property
    def success(self) -> bool:
        return self.text is not None


def fetch(request: FetchRequest[T], deadline: float | None = None,
          clock: Callable[[], float] = time.monotonic) -> FetchResult[T]:
    """Fetch and parse an HTTP response without updating any cache.

    Failed requests have no response text. A deadline limits the request
    timeout to the remaining monotonic seconds.
    """
    timeout: float = 10
    if deadline is not None:
        timeout = min(timeout, deadline - clock())
    if timeout > 0:
        try:
            response = requests.get(request.url, auth=request.auth, params=request.params, timeout=timeout)
            if response.status_code == 200:
                return FetchResult(request.parser(response.text), response.text, clock())
            logger.error("Couldn't retrieve %s (status %d)", request.url, response.status_code)
        except requests.exceptions.RequestException as error:
            # Request exception messages can include credential-bearing query strings.
            logger.error("Couldn't retrieve %s: %s", request.url, type(error).__name__)
        except (ValueError, KeyError, TypeError) as error:
            logger.error("Couldn't parse %s: %s", request.url, error)
    return FetchResult(None, None, clock())


def log_backup_file_age(path: CachePath) -> None:
    """Log the path and age of a backup in use."""
    try:
        age = max(0, time.time() - Path(path).stat().st_mtime)
        logger.warning('Using backup %s (%.0f seconds old)', path, age)
    except OSError:
        logger.warning('Using backup %s (age unavailable)', path)


def write_backup(path: CachePath, text: str) -> None:
    """Write text to a backup file atomically."""
    path = Path(path)
    pending: Path | None = None
    try:
        with NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.',
                                delete=False) as backup:
            pending = Path(backup.name)
            backup.write(text)
        pending.replace(path)
    except OSError as error:
        logger.warning('Unable to write backup %s: %s', path, error)
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError as error:
                logger.warning('Unable to remove temporary backup %s: %s', pending, error)


class CachedResource(Generic[T]):
    """A parsed HTTP resource with background refreshes and a disk fallback."""

    # The caller owns cache and retry state; workers only return fetch results.
    # Startup publishes initial data through refresh_startup() before polling begins.

    def __init__(self, url: str, parser: Callable[[str], T],
                 auth: RequestAuth | None = None, cache_path: CachePath | None = None,
                 update_interval: timedelta = timedelta(minutes=1),
                 retry_interval: timedelta = timedelta(minutes=1), params: QueryParams | None = None,
                 worker: JobSubmitter | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.request = FetchRequest(url, parser, auth, params)
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.update_interval = update_interval.total_seconds()
        self.retry_interval = retry_interval.total_seconds()
        self.worker, self.clock = worker, clock
        self.value: T | None = None
        self._next_attempt: float | None = None
        self._pending: Future[FetchResult[T]] | None = None

    def fetch(self, deadline: float | None = None) -> FetchResult[T]:
        """Fetch and parse the resource without updating its cache."""
        return fetch(self.request, deadline, self.clock)

    def accept(self, result: FetchResult[T]) -> None:
        """Apply a fetch result to the cache and refresh or retry schedule."""
        self._next_attempt = result.completed_at + (
            self.update_interval if result.success else self.retry_interval)
        if result.text is not None:
            self.value = result.value
            if self.cache_path is not None:
                write_backup(self.cache_path, result.text)

    def load_backup(self) -> T | None:
        """Return the cached value, reading its disk backup if no value is available.

        Missing or unusable backups leave the value unavailable.
        """
        if self.value is None and self.cache_path is not None:
            try:
                self.value = self.request.parser(self.cache_path.read_text())
                log_backup_file_age(self.cache_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                logger.warning("Couldn't load backup %s: %s", self.cache_path, error)
        return self.value

    def _collect(self) -> None:
        if self._pending is not None and self._pending.done():
            pending, self._pending = self._pending, None
            try:
                result = pending.result()
            except Exception as error:
                logger.error('Unexpected fetch failure for %s: %s', self.request.url, type(error).__name__)
                result = FetchResult(None, None, self.clock())
            self.accept(result)

    def get(self, deadline: float | None = None) -> T | None:
        """Return the latest value, starting a background refresh when due.

        Wait for a pending refresh until the monotonic deadline, if supplied.
        Otherwise return immediately. Return the cached value on failure or when
        the wait expires. Unfinished refreshes continue in the background.
        """
        self._collect()
        if (self._pending is None and self.worker is not None and
                (self._next_attempt is None or self.clock() >= self._next_attempt)):
            result: Future[FetchResult[T]] = Future()

            def fetch() -> None:
                try:
                    result.set_result(self.fetch())
                except Exception as error:
                    result.set_exception(error)

            try:
                self.worker.submit(self, fetch)
            except Full:
                logger.warning('Fetch queue full for %s', self.request.url)
            else:
                self._pending = result
        if self._pending is not None and deadline is not None:
            wait((self._pending,), timeout=max(0, deadline - self.clock()))
        self._collect()
        return self.value


def fetch_startup(fetch_requests: Mapping[K, FetchRequest[Any]], deadline: float,
                  clock: Callable[[], float] = time.monotonic
                  ) -> dict[K, FetchResult[Any]]:
    """Fetch named requests concurrently and return results completed by the deadline."""
    worker = WorkerPool(workers=4, name='startup')
    results: dict[K, Future[FetchResult[Any]]] = {}
    # Each job completes a private future; only the caller can publish its result.
    try:
        for key, request in fetch_requests.items():
            result: Future[FetchResult[Any]] = Future()

            def run_fetch(request: FetchRequest[Any] = request,
                          result: Future[FetchResult[Any]] = result) -> None:
                try:
                    result.set_result(fetch(request, deadline, clock))
                except Exception as error:
                    result.set_exception(error)

            try:
                worker.submit(key, run_fetch)
            except Full:
                logger.warning('Startup fetch queue full for %s', request.url)
            else:
                results[key] = result
        if not worker.wait_idle(max(0, deadline - clock())):
            logger.warning('Startup refresh budget exhausted')
        accepted: dict[K, FetchResult[Any]] = {}
        for key, result in results.items():
            if result.done():
                try:
                    candidate = result.result()
                    if candidate.completed_at <= deadline:
                        accepted[key] = candidate
                except Exception as error:
                    logger.error('Startup fetch failed for %s: %s', fetch_requests[key].url, type(error).__name__)
        return accepted
    finally:
        worker.close()


def refresh_startup(resources: Collection[CachedResource[Any]], deadline: float,
                    clock: Callable[[], float] = time.monotonic) -> None:
    """Initialize resource caches from completed fetches or disk backups."""
    candidates = fetch_startup({resource: resource.request for resource in resources}, deadline, clock)
    for resource in resources:
        if resource in candidates:
            resource.accept(candidates[resource])
        resource.load_backup()
