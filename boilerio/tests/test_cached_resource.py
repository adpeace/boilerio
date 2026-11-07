from datetime import timedelta
import json
from pathlib import Path

import pytest
import requests
import requests_mock

from boilerio.cached_resource import CachedResource, get_url_with_fallback


URL = 'https://scheduler/api/resource'


def parse_value(text):
    return json.loads(text)['value']


@pytest.mark.parametrize('failure', [
    {'status_code': 500}, {'status_code': 401},
    {'exc': requests.exceptions.Timeout},
    {'exc': requests.exceptions.ConnectionError},
    {'text': 'invalid json'}, {'json': {}}, {'json': None},
])
def test_failures_retain_valid_memory_and_disk_cache_and_delay_retry(tmp_path, failure):
    cache = tmp_path / 'resource'
    resource = CachedResource(URL, cache_path=cache, parser=parse_value,
                              update_interval=timedelta(hours=1))
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 'original'})
        assert resource.get(0) == 'original'
        original_cache = cache.read_text()
        http.get(URL, **failure)
        assert resource.get(3599) == 'original'
        assert http.call_count == 1
        assert resource.get(3600) == 'original'
        assert http.call_count == 2
        assert cache.read_text() == original_cache
        for tick in range(3601, 3660):
            assert resource.get(tick) == 'original'
        assert http.call_count == 2
        http.get(URL, json={'value': 'updated'})
        assert resource.get(3660) == 'updated'
        assert http.call_count == 3
        assert json.loads(cache.read_text()) == {'value': 'updated'}
        assert resource.get(7259) == 'updated'
        assert http.call_count == 3
        assert resource.get(7260) == 'updated'
        assert http.call_count == 4


@pytest.mark.parametrize('disk_text', [None, 'invalid json', '{}', 'null'])
def test_no_valid_sources_returns_none_and_throttles_initial_failures(tmp_path, disk_text):
    cache = tmp_path / 'resource'
    if disk_text is not None:
        cache.write_text(disk_text)
    resource = CachedResource(URL, cache_path=cache, parser=parse_value)
    with requests_mock.Mocker() as http:
        http.get(URL, status_code=503)
        for tick in range(60):
            assert resource.get(tick) is None
        assert http.call_count == 1
        assert resource.get(60) is None
        assert http.call_count == 2


def test_restart_loads_disk_fallback_and_retries_before_normal_refresh(tmp_path):
    cache = tmp_path / 'resource'
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': []})
        original = CachedResource(URL, cache_path=cache, parser=parse_value)
        assert original.get(10000) == []

        # A restart has a new monotonic clock and no in-memory value.
        restarted = CachedResource(URL, cache_path=cache, parser=parse_value,
                                   update_interval=timedelta(hours=1))
        http.get(URL, status_code=500)
        assert restarted.get(0) == []
        assert restarted.get(59) == []
        assert http.call_count == 2
        http.get(URL, json={'value': [1]})
        assert restarted.get(60) == [1]
        assert http.call_count == 3


def test_invalid_online_response_uses_valid_disk_cache_without_overwriting_it(tmp_path):
    cache = tmp_path / 'resource'
    cache.write_text('{"value": "backup"}')
    resource = CachedResource(URL, cache_path=cache, parser=parse_value)
    with requests_mock.Mocker() as http:
        http.get(URL, json={})
        assert resource.get(0) == 'backup'
    assert json.loads(cache.read_text()) == {'value': 'backup'}


def test_cache_write_failure_keeps_successful_value_and_normal_refresh(tmp_path):
    cache = tmp_path / 'missing-directory' / 'resource'
    resource = CachedResource(URL, cache_path=cache, parser=parse_value,
                              update_interval=timedelta(hours=1))
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 0})
        assert resource.get(0) == 0
        assert resource.get(60) == 0
        assert http.call_count == 1
    assert not cache.exists()


def test_auth_and_timeout_are_forwarded_without_disk_cache():
    resource = CachedResource(URL, auth=('device', 'secret'))
    with requests_mock.Mocker() as http:
        http.get(URL, text='raw text')
        assert resource.get(0) == 'raw text'
        assert http.last_request.timeout == 10
        assert http.last_request.headers['Authorization'].startswith('Basic ')


def test_failed_cache_replacement_preserves_old_backup(monkeypatch, tmp_path):
    cache = tmp_path / 'resource'
    cache.write_text('{"value": "backup"}')
    resource = CachedResource(URL, cache_path=cache, parser=parse_value)

    def cannot_replace(*args):
        raise OSError('replacement failed')

    monkeypatch.setattr(Path, 'replace', cannot_replace)
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 'new'})
        assert resource.get(0) == 'new'
    assert json.loads(cache.read_text()) == {'value': 'backup'}
    assert list(tmp_path.iterdir()) == [cache]


@pytest.mark.parametrize('interval', ['update_interval', 'retry_interval'])
@pytest.mark.parametrize('seconds', [0, -1])
def test_intervals_must_be_positive(interval, seconds):
    with pytest.raises(ValueError):
        CachedResource(URL, **{interval: timedelta(seconds=seconds)})


def test_one_shot_helper_remains_a_raw_text_fallback(tmp_path):
    cache = tmp_path / 'resource'
    with requests_mock.Mocker() as http:
        http.get(URL, text='unparsed content')
        assert get_url_with_fallback(cache, URL, None) == 'unparsed content'
        http.get(URL, status_code=500)
        assert get_url_with_fallback(cache, URL, None) == 'unparsed content'
