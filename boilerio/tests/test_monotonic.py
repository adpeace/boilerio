"""Elapsed-time controls must remain independent of wall-clock adjustments."""

from datetime import datetime
from unittest.mock import Mock

import requests_mock

from boilerio import scheduler, tempsensor


def test_polling_uses_elapsed_seconds_and_keeps_policy_on_http_failure():
    controller = scheduler.AllZoneController('http://scheduler', None, [])
    with requests_mock.Mocker() as requests:
        requests.get('http://scheduler/schedule', json={'schedule': {}, 'target_override': []})
        controller.iteration(datetime(2026, 10, 25, 0, 59, 59), 0)
        policy = controller.scheduler
        controller.iteration(datetime(2026, 10, 25, 1), 1)
        assert requests.call_count == 1
        requests.get('http://scheduler/schedule', status_code=503)
        controller.iteration(datetime(2026, 10, 25), 60)
        assert requests.call_count == 2
        assert controller.scheduler is policy


def test_unchanged_sensor_values_refresh_monotonic_freshness(monkeypatch):
    now = datetime(2026, 7, 1, 11)
    clock = Mock(wraps=tempsensor.datetime)
    clock.datetime.now.return_value = now
    monkeypatch.setattr(tempsensor, 'datetime', clock)
    ticks = iter([0, 100])
    monkeypatch.setattr(tempsensor.time, 'monotonic', lambda: next(ticks))
    sensor = tempsensor.EmonTHSensor(1, 'sensor')
    callback = Mock()
    sensor.add_callback(callback)
    msg = Mock(topic='sensor', payload='{"temperature":20,"humidity":60}')
    sensor._temp_callback(None, None, msg)
    sensor._temp_callback(None, None, msg)
    assert sensor.reading.when == now
    assert sensor.reading.received_at == 100
    callback.assert_called_once()


def test_thermostat_freshness_uses_receipt_tick_not_sensor_wall_time():
    from boilerio.thermostat import Thermostat
    boiler = Mock()
    # A later wall-clock correction must not prematurely expire this reading.
    sensor = Mock(reading=tempsensor.SensorReading(
        datetime(2000, 1, 1), 15, 60, 100))
    thermostat = Thermostat(boiler, sensor)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(699)
    boiler.on.assert_called_once()
    thermostat.interval_elapsed(701)
    boiler.off.assert_called_once()


def test_boiler_reissues_commands_after_elapsed_timeout(monkeypatch):
    mqtt = Mock()
    ticks = iter([0, 119, 121])
    monkeypatch.setattr(scheduler.time, 'monotonic', lambda: next(ticks))
    boiler = scheduler.MqttBoiler(1, mqtt, 'demand')
    boiler.on()
    boiler.on()
    assert mqtt.publish.call_count == 1
    boiler.on()
    assert mqtt.publish.call_count == 2
