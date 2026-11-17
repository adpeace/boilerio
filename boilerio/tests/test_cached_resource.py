from datetime import timedelta
import json
from pathlib import Path

import pytest
import requests
import requests_mock

from boilerio.cached_resource import CachedResource, FetchRequest, fetch_startup
from .http_helpers import Clock, InlineWorker, read_at


def make_resource(*args, **kwargs):
    resource = CachedResource(*args, worker=InlineWorker(), clock=Clock(), **kwargs)
    resource.load_backup()
    return resource


URL = 'https://scheduler/api/resource'


def parse_value(text):
    return json.loads(text)['value']


def test_startup_fetch_preserves_per_request_auth_params_and_parsers():
    clock = Clock(100)
    fetch_requests = {
        'schedule': FetchRequest(URL, parse_value, auth=('device', 'secret'), params={'kind': 'schedule'}),
        'weather': FetchRequest(URL, lambda text: float(json.loads(text)['temperature']),
                                params={'kind': 'weather', 'apikey': 'key'}),
    }
    with requests_mock.Mocker() as http:
        http.get(URL + '?kind=schedule', json={'value': [20]})
        http.get(URL + '?kind=weather&apikey=key', json={'temperature': '5.5'})
        results = fetch_startup(fetch_requests, deadline=105, clock=clock)

    assert results['schedule'].value == [20]
    assert results['weather'].value == 5.5
    sent = {request.qs['kind'][0]: request for request in http.request_history}
    assert sent['schedule'].headers['Authorization'] == 'Basic ZGV2aWNlOnNlY3JldA=='
    assert 'Authorization' not in sent['weather'].headers
    assert all(request.timeout == 5 for request in sent.values())


@pytest.mark.parametrize('failure', [
    {'status_code': 500}, {'exc': requests.exceptions.Timeout},
    {'text': 'invalid json'}, {'json': {}}, {'json': None},
])
def test_failures_retain_valid_memory_and_disk_cache_and_delay_retry(tmp_path, failure):
    cache = tmp_path / 'resource'
    resource = make_resource(URL, cache_path=cache, parser=parse_value,
                              update_interval=timedelta(hours=1))
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 'original'})
        assert read_at(resource, 0) == 'original'
        original_cache = cache.read_text()
        http.get(URL, **failure)
        assert read_at(resource, 3599) == 'original'
        assert http.call_count == 1
        assert read_at(resource, 3600) == 'original'
        assert http.call_count == 2
        assert cache.read_text() == original_cache
        assert read_at(resource, 3659) == 'original'
        assert http.call_count == 2
        http.get(URL, json={'value': 'updated'})
        assert read_at(resource, 3660) == 'updated'
        assert http.call_count == 3
        assert json.loads(cache.read_text()) == {'value': 'updated'}
        assert read_at(resource, 7259) == 'updated'
        assert http.call_count == 3
        assert read_at(resource, 7260) == 'updated'
        assert http.call_count == 4


@pytest.mark.parametrize('disk_text', [None, 'invalid json'])
def test_no_valid_sources_returns_none_and_throttles_initial_failures(tmp_path, disk_text):
    cache = tmp_path / 'resource'
    if disk_text is not None:
        cache.write_text(disk_text)
    resource = make_resource(URL, cache_path=cache, parser=parse_value)
    with requests_mock.Mocker() as http:
        http.get(URL, status_code=503)
        assert read_at(resource, 0) is None
        assert read_at(resource, 59) is None
        assert http.call_count == 1
        assert read_at(resource, 60) is None
        assert http.call_count == 2


def test_restart_loads_disk_fallback_and_retries_before_normal_refresh(tmp_path):
    cache = tmp_path / 'resource'
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': []})
        original = make_resource(URL, cache_path=cache, parser=parse_value)
        assert read_at(original, 10000) == []

        # A restart has a new monotonic clock and no in-memory value.
        restarted = make_resource(URL, cache_path=cache, parser=parse_value,
                                   update_interval=timedelta(hours=1))
        http.get(URL, status_code=500)
        assert read_at(restarted, 0) == []
        assert read_at(restarted, 59) == []
        assert http.call_count == 2
        http.get(URL, json={'value': [1]})
        assert read_at(restarted, 60) == [1]
        assert http.call_count == 3


def test_invalid_online_response_uses_valid_disk_cache_without_overwriting_it(tmp_path):
    cache = tmp_path / 'resource'
    cache.write_text('{"value": "backup"}')
    resource = make_resource(URL, cache_path=cache, parser=parse_value)
    with requests_mock.Mocker() as http:
        http.get(URL, json={})
        assert read_at(resource, 0) == 'backup'
    assert json.loads(cache.read_text()) == {'value': 'backup'}


def test_cache_write_failure_keeps_successful_value_and_normal_refresh(tmp_path):
    cache = tmp_path / 'missing-directory' / 'resource'
    resource = make_resource(URL, cache_path=cache, parser=parse_value,
                              update_interval=timedelta(hours=1))
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 0})
        assert read_at(resource, 0) == 0
        assert read_at(resource, 60) == 0
        assert http.call_count == 1
    assert not cache.exists()


def test_auth_params_and_timeout_are_forwarded_without_disk_cache():
    resource = make_resource(URL, str, auth=('device', 'secret'), params={'q': 'London,UK'})
    with requests_mock.Mocker() as http:
        http.get(URL, text='raw text')
        assert read_at(resource, 0) == 'raw text'
        assert http.last_request.timeout == 10
        assert http.last_request.headers['Authorization'].startswith('Basic ')
        assert http.last_request.qs['q'] == ['london,uk']


def test_transport_failure_does_not_log_query_credentials(caplog):
    resource = make_resource(URL, parser=str, params={'apikey': 'private-key'})
    with requests_mock.Mocker() as http:
        http.get(URL, exc=requests.exceptions.ConnectionError(URL + '?apikey=private-key'))
        assert read_at(resource, 0) is None
    assert URL in caplog.text
    assert 'ConnectionError' in caplog.text
    assert 'private-key' not in caplog.text


def test_failed_cache_replacement_preserves_old_backup(monkeypatch, tmp_path):
    cache = tmp_path / 'resource'
    cache.write_text('{"value": "backup"}')
    resource = make_resource(URL, cache_path=cache, parser=parse_value)

    def cannot_replace(*args):
        raise OSError('replacement failed')

    monkeypatch.setattr(Path, 'replace', cannot_replace)
    with requests_mock.Mocker() as http:
        http.get(URL, json={'value': 'new'})
        assert read_at(resource, 0) == 'new'
    assert json.loads(cache.read_text()) == {'value': 'backup'}
    assert list(tmp_path.iterdir()) == [cache]
