"""Fetch resources with a disk fallback and control-loop-friendly retries."""

from datetime import timedelta
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests


logger = logging.getLogger(__name__)


class CachedResource:
    """Retain a parsed resource across calls and service failures.

    ``get(tick)`` takes monotonic seconds and makes at most one HTTP request
    when due. Failed attempts use a separate retry interval; no retry sleeps
    block the caller. The parser must raise ValueError, KeyError, or TypeError
    for invalid content. Only successfully parsed responses replace the cache.
    Disk data is a startup fallback, not evidence of a successful refresh.
    """

    def __init__(self, url, auth=None, cache_path=None, parser=str,
                 update_interval=timedelta(minutes=1),
                 retry_interval=timedelta(minutes=1)):
        self.url = url
        self.auth = auth
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.parser = parser
        self.update_interval = update_interval.total_seconds()
        self.retry_interval = retry_interval.total_seconds()
        if self.update_interval <= 0 or self.retry_interval <= 0:
            raise ValueError('Refresh and retry intervals must be positive')
        self._value = None
        self._next_attempt = None
        self._disk_cache_checked = False

    def get(self, tick):
        """Return the last valid value, or None if no source is available."""
        if self._next_attempt is not None and tick < self._next_attempt:
            return self._value

        # Advance the deadline even on HTTP, transport, or parsing failure.
        self._next_attempt = tick + self.retry_interval
        try:
            response = requests.get(self.url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                value = self.parser(response.text)
                self._value = value
                self._next_attempt = tick + self.update_interval
                self._save(response.text)
                return value
            logger.error("Couldn't retrieve %s (status %d)",
                         self.url, response.status_code)
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error("Couldn't retrieve or parse %s: %s", self.url, e)

        if self._value is None and not self._disk_cache_checked:
            self._disk_cache_checked = True
            if self.cache_path is not None:
                try:
                    self._value = self.parser(self.cache_path.read_text())
                except (OSError, ValueError, KeyError, TypeError) as e:
                    logger.error("Couldn't load backup file %s: %s", self.cache_path, e)
        return self._value

    def _save(self, text):
        if self.cache_path is not None:
            pending = None
            try:
                # Keep the previous backup intact if writing is interrupted.
                with NamedTemporaryFile(mode='w', dir=self.cache_path.parent,
                                        prefix=self.cache_path.name + '.',
                                        delete=False) as backup:
                    pending = Path(backup.name)
                    backup.write(text)
                pending.replace(self.cache_path)
            except OSError as e:
                logger.warning("Unable to write backup file %s: %s", self.cache_path, e)
            finally:
                if pending is not None:
                    try:
                        pending.unlink(missing_ok=True)
                    except OSError as e:
                        logger.warning("Unable to remove temporary backup %s: %s", pending, e)


def get_url_with_fallback(fallback, url, auth):
    """Fetch raw text once, using a disk backup if the request fails.

    Stateful callers should retain a CachedResource with their parser instead.
    """
    return CachedResource(url, auth, fallback).get(0)
