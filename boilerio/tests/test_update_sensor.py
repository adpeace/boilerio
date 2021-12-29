from ..update_sensor import TempSensorUpdater
from ..tempsensor import SensorReading
from unittest.mock import MagicMock
from datetime import datetime
import requests_mock

class MockSensor:
    def __init__(self):
        self.reading = None
        self.callback = None
        self.sensor_id = 1

    def add_callback(self, callback):
        self.callback = callback

    def update(self, when, temp, humidity):
        self.reading = SensorReading(when, temp, humidity)
        self.callback(self)

def test_adding_sensor_register_a_callback():
    # Given: a TempSensorUpdator and sensor
    sensor = MagicMock()
    updater = TempSensorUpdater('http://foo/', None)

    # When: adding the sensor to the updater
    updater.add_sensor(sensor)

    # Then: a callback for updates is registered
    assert sensor.add_callback.called

def test_sensor_update_causes_updates_to_be_published():
    # Given: a TempSensorUpdator and mock sensor
    updater = TempSensorUpdater('http://foo', None)
    sensor = MockSensor()
    updater.add_sensor(sensor)

    # When: the temperature changes
    with requests_mock.Mocker() as m:
        m.post('http://foo/sensor/1/readings', status_code=200)
        sensor.update(datetime.now(), 15.0, 50.0)

        # Then: the update is posted to the backend
        assert m.call_count == 2

def test_sensor_update_doesnt_leak_exception_on_failed_post():
    # Given: a TempSensorUpdator and mock sensor
    updater = TempSensorUpdater('http://foo', None)
    sensor = MockSensor()
    updater.add_sensor(sensor)

    # When: the temperature changes
    with requests_mock.Mocker() as m:
        m.post('http://foo/sensor/1/readings', status_code=401)
        sensor.update(datetime.now(), 15.0, 50.0)

        # Then: the update is posted to the backend
        assert m.called