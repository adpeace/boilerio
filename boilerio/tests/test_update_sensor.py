from ..update_sensor import TempSensorUpdater
from .. import tempsensor
from ..tempsensor import EmonTHSensor, SensorReading
from unittest.mock import MagicMock
from datetime import datetime, timezone
import requests_mock
import json
from .http_helpers import InlineWorker

class MockSensor:
    def __init__(self):
        self.reading = None
        self.callback = None
        self.sensor_id = 1

    def add_callback(self, callback):
        self.callback = callback

    def update(self, when, temp, humidity):
        self.reading = SensorReading(when, temp, humidity, 0)
        self.callback(self)

def test_adding_sensor_register_a_callback():
    # Given: a TempSensorUpdator and sensor
    sensor = MagicMock()
    updater = TempSensorUpdater('http://foo/', None, InlineWorker())

    # When: adding the sensor to the updater
    updater.add_sensor(sensor)

    # Then: a callback for updates is registered
    assert sensor.add_callback.called

def test_sensor_update_causes_updates_to_be_published():
    # Given: a TempSensorUpdator and mock sensor
    updater = TempSensorUpdater('http://foo', None, InlineWorker())
    sensor = MockSensor()
    updater.add_sensor(sensor)

    # When: the temperature changes
    with requests_mock.Mocker() as m:
        m.post('http://foo/sensor/1/readings', status_code=200)
        sensor.update(datetime.now(timezone.utc), 15.0, 50.0)

        # Then: the update is posted to the backend
        assert m.call_count == 2

def test_sensor_update_doesnt_leak_exception_on_failed_post():
    # Given: a TempSensorUpdator and mock sensor
    updater = TempSensorUpdater('http://foo', None, InlineWorker())
    sensor = MockSensor()
    updater.add_sensor(sensor)

    # When: the temperature changes
    with requests_mock.Mocker() as m:
        m.post('http://foo/sensor/1/readings', status_code=401)
        sensor.update(datetime.now(timezone.utc), 15.0, 50.0)

        # Then: the update is posted to the backend
        assert m.called


def test_sensor_upload_keeps_offset_and_microseconds():
    updater = TempSensorUpdater('http://foo', None, InlineWorker())
    when = datetime.fromisoformat('2026-07-01T12:34:56.123456+01:00')
    with requests_mock.Mocker() as m:
        m.post('http://foo/sensor/1/readings', status_code=200)
        updater._publish_updated_value('http://foo/sensor/1/readings', 'temperature', when, 20)
        assert m.last_request.json()['when'] == '2026-07-01T12:34:56.123456+01:00'


def report(sensor, **changes):
    data = {'temperature': '18.59', 'humidity': '67.8', 'battery': '1.2', **changes}
    sensor._temp_callback(None, None, MagicMock(topic=sensor.locator, payload=json.dumps(data)))


def test_unchanged_reports_make_no_api_calls_until_fifteen_minutes(monkeypatch):
    tick = [0]
    monkeypatch.setattr(tempsensor.time, 'monotonic', lambda: tick[0])
    sensor = EmonTHSensor(5, 'emon_sensors/emonth5')
    updater = TempSensorUpdater('http://foo', None, InlineWorker())
    updater.add_sensor(sensor)
    with requests_mock.Mocker() as requests:
        requests.post('http://foo/sensor/5/readings', status_code=200)
        report(sensor)
        tick[0] = 60
        report(sensor)
        tick[0] = 899
        report(sensor)
        assert requests.call_count == 3
        tick[0] = 900
        report(sensor)
        tick[0] = 901
        report(sensor, battery='1.1')
        tick[0] = 902
        report(sensor, battery='1.1')

        bodies = [request.json() for request in requests.request_history]
        assert [body['metric_type'] for body in bodies] == [
            'temperature', 'humidity', 'battery_voltage',
            'temperature', 'humidity', 'battery_voltage', 'battery_voltage',
        ]
        assert bodies[-2]['value'] == 1.2
        assert bodies[-1]['value'] == 1.1
        assert datetime.fromisoformat(bodies[-1]['when']).utcoffset().total_seconds() == 0


def test_only_changed_metrics_are_uploaded():
    sensor = EmonTHSensor(5, 'emon_sensors/emonth5')
    TempSensorUpdater('http://foo', None, InlineWorker()).add_sensor(sensor)
    with requests_mock.Mocker() as requests:
        requests.post('http://foo/sensor/5/readings', status_code=200)
        report(sensor)
        report(sensor, temperature='19')
        report(sensor, temperature='19', humidity='68')
        report(sensor, temperature='19', humidity='68', battery='1.1')
        report(sensor, temperature='19', humidity='68', battery='1.1')
        assert [request.json()['metric_type'] for request in requests.request_history] == [
            'temperature', 'humidity', 'battery_voltage', 'temperature', 'humidity', 'battery_voltage',
        ]


def test_failed_metric_is_retried_without_reposting_successful_metrics():
    sensor = EmonTHSensor(5, 'emon_sensors/emonth5')
    TempSensorUpdater('http://foo', None, InlineWorker()).add_sensor(sensor)
    with requests_mock.Mocker() as requests:
        requests.post('http://foo/sensor/5/readings', [
            {'status_code': 200}, {'status_code': 200}, {'status_code': 503}, {'status_code': 200},
        ])
        report(sensor)
        assert [request.json()['metric_type'] for request in requests.request_history] == [
            'temperature', 'humidity', 'battery_voltage',
        ]
        # The failed voltage upload must be retried, even when unchanged.
        report(sensor)
        assert requests.call_count == 4
        assert requests.last_request.json()['metric_type'] == 'battery_voltage'


def test_reporting_interval_is_per_sensor():
    updater = TempSensorUpdater('http://foo', None, InlineWorker())
    with requests_mock.Mocker() as requests:
        requests.post('http://foo/sensor/5/readings', status_code=200)
        requests.post('http://foo/sensor/6/readings', status_code=200)
        for sensor_id in (5, 6):
            sensor = EmonTHSensor(sensor_id, f'emon_sensors/emonth{sensor_id}')
            updater.add_sensor(sensor)
            report(sensor)
            report(sensor)
        assert requests.call_count == 6
