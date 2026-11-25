from boilerio import monitor
from boilerio.weather import WeatherReading, Weather, WEATHER_API_ENDPOINT
from pathlib import Path
import json
from configparser import RawConfigParser
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests_mock
from flask import Flask, request
from boilerio.backend.util import csrf_protection
from .http_helpers import Clock, InlineWorker

def test_none_to_on_transition_no_reading():
    """Test that when the boiler turns on for the first time that
    a temperature reading provided shortly afterwards doesn't cause
    a gradient to be generated."""
    m = monitor.Monitor()
    t = 0.0
    m.set_outside_temperature(10, t)
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)
    assert m.temperature_update(22, t + 10) == None

def test_first_ten_minutes_are_ignored():
    """Check that warmup period is ignored."""
    m = monitor.Monitor(warmup_interval_s=60)
    t = 0.0
    m.set_outside_temperature(10, t)
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)
    assert m.temperature_update(21, t + 120) == None
    assert m.temperature_update(23, t + 1320) == (11, 6.0)

def test_boiler_already_on():
    """Check that multiple boiler on messages don't cause a problem."""
    m = monitor.Monitor(warmup_interval_s=60)
    t = 0.0
    m.set_outside_temperature(10, t)

    # First update should not capture temperature because the boiler isn't on long enough
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)

    # Next update should be captured:
    m.boiler_on(t + 119)
    assert m.temperature_update(21, t + 120) == None

    # Final update should produce a result:
    m.boiler_on(t + 1319)
    assert m.temperature_update(23, t + 1320) == (11, 6.0)


@pytest.fixture
def monitor_client(monkeypatch, tmp_path):
    config = RawConfigParser()
    config.read_dict({
        'heating': {'scheduler_url': 'https://scheduler', 'info_basetopic': 'heating/zone/info'},
        'mqtt': {'host': 'broker', 'user': 'user', 'password': 'password'},
        'weather': {'apikey': 'test', 'location': 'London,UK'},
    })
    monkeypatch.setattr(monitor.config, 'load_config', lambda: config)
    (tmp_path / 'monitor-configuration').write_text(json.dumps({
        'system': {'timezone': 'Europe/London'},
        'sensors': [{'sensor_id': 2, 'locator': 'sensors/living'}],
        'zones': [{'zone_id': 7, 'name': 'Living room', 'boiler_relay': '0xBA', 'sensor_id': 2}],
    }))
    monkeypatch.setattr(monitor, 'Path', lambda configured_path: tmp_path / Path(configured_path).name)
    monkeypatch.setattr(monitor.requests, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=503))
    worker = Mock()
    worker.submit.side_effect = InlineWorker().submit
    monkeypatch.setattr(monitor, 'WorkerPool', lambda **kwargs: worker)
    mqtt = Mock()
    monkeypatch.setattr(monitor.mqtt, 'Client', Mock(return_value=mqtt))
    return mqtt


def test_offline_monitor_subscribes_to_sensor_from_monitor_snapshot(monitor_client):
    mqtt = monitor_client
    mqtt.loop_forever.side_effect = lambda: mqtt.on_connect(
        mqtt, None, None, SimpleNamespace(is_failure=False), None)

    monitor.main()

    mqtt.subscribe.assert_any_call('sensors/living')


def test_monitor_keeps_previous_weather_until_hourly_refresh_recovers():
    clock = Clock()
    weather = Weather('apikey', 'London,UK', worker=InlineWorker(), clock=clock)
    worker = monitor.MqttMonitor(Mock(), 'relay', 'sensor', weather, Mock())
    message = SimpleNamespace(topic='sensor', payload='{"temperature": 20}')
    response = {'main': {'temp': 10, 'humidity': 76},
                'sys': {'sunrise': 0, 'sunset': 0}}
    updated = dict(response, main={'temp': 12, 'humidity': 76})
    with requests_mock.Mocker() as http:
        http.get(WEATHER_API_ENDPOINT, [
            {'json': response}, {'status_code': 503}, {'json': updated},
        ])
        for tick, count, temperature in [
                (0, 1, 10), (3599, 1, 10), (3600, 2, 10),
                (3659, 2, 10), (3660, 3, 12)]:
            clock.value = tick
            worker.mqtt_temperature_update(None, None, message)
            assert http.call_count == count
            assert worker._outside_temperature == temperature


def test_missing_weather_is_retried_on_next_sensor_report():
    weather = Mock()
    weather.get_weather.side_effect = [None, WeatherReading(10, 76, 0, 0)]
    worker = monitor.MqttMonitor(Mock(), 'relay', 'sensor', weather, Mock())
    message = SimpleNamespace(topic='sensor', payload='{"temperature": 20}')

    worker.mqtt_temperature_update(None, None, message)
    assert worker._outside_temperature is None
    worker.mqtt_temperature_update(None, None, message)
    assert worker._outside_temperature == 10


def test_monitor_can_post_gradient_to_csrf_protected_endpoint(monkeypatch, monitor_client):
    web = Flask(__name__)
    measurements = []

    @web.post('/zones/7/gradient_measurements')
    @csrf_protection
    def receive_gradient():
        measurements.append(request.get_json())
        return '', 200

    client = web.test_client()
    monkeypatch.setattr(monitor.requests, 'post',
                        lambda url, json, headers=None, **kwargs:
                        client.post(url, json=json, headers=headers))
    monkeypatch.setattr(monitor.weather.Weather, 'get_weather',
                        lambda self: WeatherReading(10, 76, 0, 0))
    monkeypatch.setattr(monitor.Monitor, 'temperature_update', lambda *args: (10, 2))
    callbacks = {}
    monitor_client.message_callback_add.side_effect = lambda topic, handler: callbacks.update({topic: handler})
    monitor_client.loop_forever.side_effect = lambda: callbacks['sensors/living'](
        None, None, SimpleNamespace(topic='sensors/living', payload='{"temperature": 20}'))

    monitor.main()

    assert len(measurements) == 1
    assert measurements[0]['delta'] == 10
    assert measurements[0]['gradient'] == 2
