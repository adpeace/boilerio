from boilerio import monitor
from boilerio.schedulerweb.model import Zone
from boilerio.tempsensor import EmonTHSensor
from configparser import RawConfigParser
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask, request
from boilerio.schedulerweb.util import csrf_protection

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
def monitor_client(monkeypatch):
    config = RawConfigParser()
    config.read_dict({
        'heating': {'scheduler_url': 'https://scheduler', 'info_basetopic': 'heating/zone/info'},
        'mqtt': {'host': 'broker', 'user': 'user', 'password': 'password'},
        'weather': {'apikey': 'test', 'location': 'London,UK'},
    })
    monkeypatch.setattr(monitor.config, 'load_config', lambda: config)
    monkeypatch.setattr(monitor.scheduler, 'load_zone_info',
                        lambda url, auth: [Zone(7, 'Living room', '0xBA', 2)])
    load_sensors = Mock(return_value={2: EmonTHSensor(2, 'sensors/living')})
    monkeypatch.setattr(monitor.scheduler, 'construct_sensors', load_sensors)
    mqtt = Mock()
    monkeypatch.setattr(monitor.mqtt, 'Client', Mock(return_value=mqtt))
    return mqtt


def test_main_reaches_mqtt_loop_with_zone_sensor_id(monitor_client):
    mqtt = monitor_client
    mqtt.loop_forever.side_effect = lambda: mqtt.on_connect(
        mqtt, None, None, SimpleNamespace(is_failure=False), None)

    monitor.main()

    mqtt.loop_forever.assert_called_once()


@pytest.mark.parametrize('ticks,expected_fetches', [
    ([0, 1, 3599, 3600, 3601], [1, 1, 1, 2, 2]),
    ([0, 7200, 7201], [1, 2, 2]),
])
def test_weather_refreshes_only_when_due_including_after_long_gaps(
        monkeypatch, ticks, expected_fetches):
    clock = iter(ticks)
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: next(clock))
    weather = Mock()
    weather.get_weather.return_value = {'temperature': 10}
    worker = monitor.MqttMonitor(Mock(), 'relay', 'sensor', weather, Mock(),
                                 weather_update_interval_s=3600)
    message = SimpleNamespace(topic='sensor', payload='{"temperature": 20}')

    for count in expected_fetches:
        worker.mqtt_temperature_update(None, None, message)
        assert weather.get_weather.call_count == count


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
                        lambda self: {'temperature': 10})
    monkeypatch.setattr(monitor.Monitor, 'temperature_update', lambda *args: (10, 2))
    callbacks = {}
    monitor_client.message_callback_add.side_effect = lambda topic, handler: callbacks.update({topic: handler})
    monitor_client.loop_forever.side_effect = lambda: callbacks['sensors/living'](
        None, None, SimpleNamespace(topic='sensors/living', payload='{"temperature": 20}'))

    monitor.main()

    assert len(measurements) == 1
    assert measurements[0]['delta'] == 10
    assert measurements[0]['gradient'] == 2
