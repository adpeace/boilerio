"""Network behaviour at startup and during heating control."""

from configparser import RawConfigParser
from datetime import datetime, timezone
import json
import os
from queue import Full
from threading import Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from boilerio import cached_resource, scheduler, startup, tempsensor, update_sensor, zones
from boilerio.background import WorkerPool
from boilerio.cached_resource import CachedResource, refresh_startup
from boilerio.weather import WEATHER_API_ENDPOINT
from .http_helpers import Clock, HeldWorker, InlineWorker


URL = 'http://scheduler'
MONDAY = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def response(data, status=200):
    return SimpleNamespace(status_code=status, text=json.dumps(data),
                           raise_for_status=lambda: None)


def schedule(target):
    return {'schedule': {'0': [{'when': '00:00', 'zones': [{'zone': 1, 'temp': target}]}]},
            'target_override': []}


def configuration(timezone, sensor_id, relay):
    return {
        'system': {'timezone': timezone},
        'sensors': [{'sensor_id': sensor_id, 'locator': f'sensors/{sensor_id}'}],
        'zones': [{'zone_id': 1, 'name': 'Room', 'boiler_relay': relay, 'sensor_id': sensor_id}],
    }


@pytest.fixture
def online(monkeypatch):
    config = configuration('Europe/London', 2, '0x1')
    payloads = {
        URL + '/system': config['system'],
        URL + '/sensor/': config['sensors'],
        URL + '/zones': config['zones'],
        URL + '/schedule': schedule(22),
        URL + '/zones/1/gradients': [{'delta': 10, 'gradient': 1}],
        WEATHER_API_ENDPOINT: {'main': {'temp': 5, 'humidity': 70},
                               'sys': {'sunrise': 0, 'sunset': 0}},
    }
    monkeypatch.setattr(requests, 'get', lambda url, **kwargs: response(payloads[url]))
    return payloads


@pytest.fixture
def pools():
    fetch, upload = WorkerPool(name='test-fetch'), WorkerPool(name='test-upload')
    try:
        yield fetch, upload
    finally:
        for pool in (fetch, upload):
            pool.close()
            assert pool.wait_idle(3)


def build_controller(cache_dir, workers, mqtt, clock=time.monotonic):
    conf = RawConfigParser()
    conf.read_dict({'heating': {'demand_request_topic': 'demand'},
                    'weather': {'apikey': 'key', 'location': 'London,UK'}})
    return scheduler.build_controller(conf, URL, None, mqtt, *workers,
                                      cache_dir=cache_dir, clock=clock)


def test_scheduler_starts_with_online_schedule_gradients_and_weather(tmp_path, online):
    (tmp_path / 'schedule').write_text(json.dumps(schedule(16)))
    mqtt = Mock()
    controller, _ = build_controller(tmp_path, (InlineWorker(), InlineWorker()), mqtt)
    zone = controller.zone_controllers[0]

    assert controller._schedule_resource.value.target(MONDAY, 1) == 22
    assert zone._gradient_resource.value == [{'delta': 10, 'gradient': 1}]
    assert zone.weather._resource.value.temperature == 5
    mqtt.publish.assert_not_called()


def test_scheduler_refreshes_startup_weather_after_twenty_minutes(tmp_path, online):
    clock = Clock()
    controller, _ = build_controller(tmp_path, (InlineWorker(), InlineWorker()), Mock(), clock)
    weather = controller.zone_controllers[0].weather
    online[WEATHER_API_ENDPOINT]['main']['temp'] = 10

    clock.value = 1199
    assert weather.get_weather().temperature == 5
    clock.value = 1200
    assert weather.get_weather().temperature == 10


def test_configuration_and_schedule_share_the_startup_deadline(monkeypatch, tmp_path, online):
    clock = Clock()
    # Run requests in order so each response advances the same logical clock.
    pool = Mock()
    pool.submit.side_effect = InlineWorker().submit
    pool.wait_idle.return_value = True
    monkeypatch.setattr(cached_resource, 'WorkerPool', lambda **kwargs: pool)
    (tmp_path / 'schedule').write_text(json.dumps(schedule(16)))

    def get(url, **kwargs):
        if url.endswith('/system'):
            clock.value = 8
        if url.endswith('/schedule'):
            clock.value = 31
        return response(online[url])

    monkeypatch.setattr(requests, 'get', get)
    controller, _ = build_controller(tmp_path, (InlineWorker(), InlineWorker()), Mock(), clock)
    assert controller._schedule_resource.value.target(MONDAY, 1) == 16
    assert json.loads((tmp_path / 'schedule').read_text()) == schedule(16)


def test_independent_startup_fetch_can_run_while_first_request_is_blocked(monkeypatch):
    fast_started = Event()

    def get(url, **kwargs):
        if url.endswith('/first'):
            if not fast_started.wait(2):
                return response({}, 503)
        else:
            fast_started.set()
        return response(1)

    monkeypatch.setattr(requests, 'get', get)
    resources = [CachedResource(URL + path, int) for path in ('/first', '/second')]
    refresh_startup(resources, time.monotonic() + 3)
    assert [resource.value for resource in resources] == [1, 1]


def test_startup_without_online_or_cached_configuration_fails_before_control(monkeypatch, tmp_path):
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response({}, 503))
    mqtt = Mock()
    with pytest.raises(ValueError, match='No valid startup'):
        build_controller(tmp_path, (InlineWorker(), InlineWorker()), mqtt)
    mqtt.publish.assert_not_called()


@pytest.mark.parametrize('failure', ['missing zones', 'unmatched sensor'])
def test_unusable_online_configuration_preserves_whole_snapshot_and_its_age(
        monkeypatch, tmp_path, online, failure):
    path = tmp_path / 'configuration'
    previous = configuration('UTC', 3, '0x2')
    original = json.dumps(previous)
    path.write_text(original)
    os.utime(path, (100, 100))
    if failure == 'missing zones':
        monkeypatch.setattr(requests, 'get', lambda url, **kwargs:
                            response({}, 503) if url.endswith('/zones') else response(online[url]))
    else:
        online[URL + '/zones'][0]['sensor_id'] = 99

    restored = startup.load_configuration(URL, None, time.monotonic() + 3, path)
    assert restored.timezone.key == 'UTC'
    assert restored.zones[0].sensor_id == 3
    assert set(restored.sensors) == {3}
    assert path.read_text() == original
    assert path.stat().st_mtime == 100


def test_offline_boot_loads_entire_latest_online_configuration(monkeypatch, tmp_path, online):
    path = tmp_path / 'configuration'
    path.write_text(json.dumps(configuration('UTC', 3, '0x2')))
    startup.load_configuration(URL, None, time.monotonic() + 3, path)

    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response({}, 503))
    restored = startup.load_configuration(URL, None, time.monotonic() + 3, path)
    assert restored.timezone.key == 'Europe/London'
    zone, = restored.zones
    assert (zone.zone_id, zone.name, zone.boiler_relay, zone.sensor_id) == (1, 'Room', '0x1', 2)
    assert set(restored.sensors) == {2}
    assert restored.sensors[2].locator == 'sensors/2'


@pytest.mark.parametrize('invalid_part', ['timezone', 'missing system', 'sensor reference'])
def test_invalid_snapshot_cannot_supply_partial_startup_configuration(monkeypatch, tmp_path, invalid_part):
    path = tmp_path / 'configuration'
    data = configuration('Europe/London', 2, '0x1')
    if invalid_part == 'timezone':
        data['system']['timezone'] = 'Invalid/Zone'
    elif invalid_part == 'missing system':
        del data['system']
    else:
        data['zones'][0]['sensor_id'] = 3
    path.write_text(json.dumps(data))
    monkeypatch.setattr(requests, 'get', lambda url, **kwargs:
                        response({'timezone': 'UTC'}) if url.endswith('/system') else response({}, 503))
    with pytest.raises(ValueError, match='No valid startup configuration'):
        startup.load_configuration(URL, None, time.monotonic() + 3, path)


def test_expired_startup_fetch_cannot_prevent_or_overwrite_runtime_refresh(monkeypatch, tmp_path, caplog):
    cache = tmp_path / 'value'
    cache.write_text('"backup"')
    resource = CachedResource(URL, json.loads, cache_path=cache, worker=InlineWorker())
    release = Event()
    startup_pool = WorkerPool()
    monkeypatch.setattr(cached_resource, 'WorkerPool', lambda **kwargs: startup_pool)
    startup_request, finished = Event(), Event()

    def get(*args, **kwargs):
        if not startup_request.is_set():
            startup_request.set()
            release.wait(3)
            finished.set()
            return response('late startup')
        return response('runtime')

    monkeypatch.setattr(requests, 'get', get)
    try:
        refresh_startup([resource], time.monotonic() + 0.2)
        assert startup_request.is_set()
        assert resource.value == 'backup'
        assert 'seconds old' in caplog.text
        assert resource.get() == 'runtime'
        assert not finished.is_set()
    finally:
        release.set()
        startup_pool.close()
        assert startup_pool.wait_idle(3)
    assert resource.value == 'runtime'
    assert json.loads(cache.read_text()) == 'runtime'


def test_fetch_queue_rejection_keeps_cached_value_until_next_read(monkeypatch, tmp_path):
    worker = Mock()
    worker.submit.side_effect = Full
    cache = tmp_path / 'value'
    cache.write_text('"backup"')
    resource = CachedResource(URL, json.loads, cache_path=cache, worker=worker)
    resource.load_backup()
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response('fresh'))

    assert resource.get() == 'backup'
    worker.submit.side_effect = InlineWorker().submit
    assert resource.get() == 'fresh'


def test_due_cached_read_waits_for_fresh_value_within_deadline(monkeypatch, tmp_path, pools):
    cache = tmp_path / 'value'
    cache.write_text('"backup"')
    resource = CachedResource(URL, json.loads, cache_path=cache, worker=pools[0])
    resource.load_backup()
    started, release = Event(), Event()
    values = []

    def get(*args, **kwargs):
        started.set()
        release.wait(3)
        return response('fresh')

    monkeypatch.setattr(requests, 'get', get)
    reader = Thread(target=lambda: values.append(resource.get(time.monotonic() + 2)), daemon=True)
    try:
        reader.start()
        assert started.wait(2)
        reader.join(0.05)
        assert reader.is_alive()  # The caller waits for fresh data while time remains.
    finally:
        release.set()
        reader.join(3)
    assert values == ['fresh']


def test_timed_out_refresh_publishes_once_on_next_caller_read(monkeypatch, tmp_path):
    cache = tmp_path / 'value'
    cache.write_text('"backup"')
    worker = HeldWorker()
    resource = CachedResource(URL, json.loads, cache_path=cache, worker=worker)
    resource.load_backup()
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response('fresh'))

    assert resource.get(deadline=time.monotonic() + 0.01) == 'backup'
    assert resource.get() == 'backup'
    assert len(worker.jobs) == 1
    worker.run_next()
    assert resource.value == 'backup'
    assert json.loads(cache.read_text()) == 'backup'
    assert resource.get() == 'fresh'
    assert json.loads(cache.read_text()) == 'fresh'
    assert not worker.jobs


def test_schedule_gradients_and_weather_share_one_iteration_deadline(monkeypatch, tmp_path, online):
    clock = Clock(100)
    controller, _ = build_controller(tmp_path, (InlineWorker(), InlineWorker()), Mock(), clock)
    zone = controller.zone_controllers[0]
    deadlines = {}

    def read_schedule(deadline=None):
        deadlines['schedule'] = deadline
        clock.value += 3
        return controller._schedule_resource.value

    def read_gradients(deadline=None):
        deadlines['gradients'] = deadline
        clock.value += 1

    def read_weather(deadline=None):
        deadlines['weather'] = deadline

    monkeypatch.setattr(controller._schedule_resource, 'get', read_schedule)
    monkeypatch.setattr(zone._gradient_resource, 'get', read_gradients)
    monkeypatch.setattr(zone.weather, 'get_weather', read_weather)
    monkeypatch.setattr(zone, 'report_updated_state', lambda tick: None)
    controller.iteration(MONDAY, 100)
    assert deadlines == {'schedule': 105, 'gradients': 105, 'weather': 105}


def report_temperature(sensor, temperature):
    sensor._temp_callback(None, None, SimpleNamespace(
        topic=sensor.locator, payload=json.dumps({'temperature': temperature, 'humidity': 70})))


def test_sensor_upload_and_heat_demand_continue_while_fetch_pool_is_blocked(
        monkeypatch, tmp_path, online, pools):
    clock = Clock(time.monotonic() - 3601)
    mqtt = Mock()
    controller, sensors = build_controller(tmp_path, pools, mqtt, clock)
    sensor = sensors[2]
    clock.value = time.monotonic()
    monkeypatch.setattr(controller, 'FETCH_WAIT_SECONDS', 0)
    schedule_started, gradients_started, uploaded, release = Event(), Event(), Event(), Event()

    def get(url, **kwargs):
        if url.endswith('/schedule'):
            schedule_started.set()
        elif url.endswith('/gradients'):
            gradients_started.set()
        release.wait(3)
        return response(online[url])

    def post(url, **kwargs):
        if url.endswith('/sensor/2/readings') and kwargs['json']['metric_type'] == 'temperature':
            uploaded.set()
        return response({})

    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(requests, 'post', post)
    try:
        controller.iteration(MONDAY, clock())
        assert schedule_started.wait(2)
        assert gradients_started.wait(2)
        report_temperature(sensor, 18)
        assert uploaded.wait(1)
        controller.iteration(MONDAY, clock())
        assert json.loads(mqtt.publish.call_args.args[1])['command'] == 'O'
    finally:
        release.set()
        assert all(pool.wait_idle(3) for pool in pools)


def test_sensor_uploads_coalesce_and_keep_original_timestamps(monkeypatch, pools):
    worker = pools[1]
    sensor = tempsensor.EmonTHSensor(2, 'sensors/2')
    update_sensor.TempSensorUpdater(URL, None, worker).add_sensor(sensor)
    started, release = Event(), Event()
    sent = []

    def post(url, **kwargs):
        if kwargs['json']['metric_type'] == 'temperature':
            sent.append((kwargs['json'], kwargs['timeout']))
            if len(sent) == 1:
                started.set()
                release.wait(3)
        return response({})

    monkeypatch.setattr(requests, 'post', post)
    try:
        report_temperature(sensor, 18)
        assert started.wait(2)
        report_temperature(sensor, 19)
        report_temperature(sensor, 20)
        when = sensor.reading.when.isoformat()
    finally:
        release.set()
        assert worker.wait_idle(3)
    assert [(body['value'], timeout) for body, timeout in sent] == [(18, 10), (20, 10)]
    assert sent[-1][0]['when'] == when


def test_reverting_to_last_ack_while_upload_is_pending_reports_the_reversion(monkeypatch):
    worker = HeldWorker()
    sensor = SimpleNamespace(reading=SimpleNamespace(temperature=18))
    weather = Mock()
    weather.get_weather.return_value = None
    controller = zones.ZoneController(SimpleNamespace(zone_id=1), Mock(), sensor,
                                      Mock(target=20, is_heating=False), URL, None, weather,
                                      upload_worker=worker)
    policy = Mock()
    policy.target.return_value = 20
    policy.target_overridden.return_value = False
    sent = []

    def post(url, **kwargs):
        sent.append(kwargs['json']['current_temp'])
        return response({})

    monkeypatch.setattr(requests, 'post', post)
    controller.iteration(policy, MONDAY, 0)
    worker.run_next()
    controller.iteration(policy, MONDAY, 1)
    sensor.reading.temperature = 19
    controller.iteration(policy, MONDAY, 2)
    sensor.reading.temperature = 18
    controller.iteration(policy, MONDAY, 3)
    worker.run_next()
    # Only the next control iteration may collect the acknowledgement of 19.
    assert not controller._should_report_state(3)
    controller.iteration(policy, MONDAY, 4)
    worker.run_next()
    controller.iteration(policy, MONDAY, 5)
    assert sent == [18, 19, 18]
    assert not worker.jobs


def test_next_refresh_is_due_one_interval_after_fetch_completes(monkeypatch):
    clock, worker = Clock(), HeldWorker()
    resource = CachedResource(URL, int, worker=worker, clock=clock)
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response(1))

    assert resource.get() is None
    clock.value = 130
    worker.run_next()
    clock.value = 189
    assert resource.get() == 1
    assert not worker.jobs
    clock.value = 190
    resource.get()
    assert len(worker.jobs) == 1
