import datetime
import pytest
from ..thermostat import Thermostat
from ..tempsensor import SensorReading

class FakeBoiler(object):
    def __init__(self):
        self.last_command = None

    def on(self):
        self.last_command = 'O'

    def off(self):
        self.last_command = 'X'

class MockSensor(object):
    def __init__(self):
        self.reading = None

    def set_temp(self, temp):
        self.reading = temp

@pytest.fixture
def sensor():
    yield MockSensor()

@pytest.fixture
def boiler():
    yield FakeBoiler()

@pytest.fixture
def thermostat(boiler, sensor):
    yield Thermostat(boiler, sensor)

def test_start_off_if_above_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = SensorReading(now, 20, 60)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(15)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'

def test_start_on_if_below_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = SensorReading(now, 15, 60)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'O'

def test_start_pwn_if_at_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = SensorReading(now, 20, 60)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    # not ideal:
    assert thermostat._measurement_begin == now

def test_stale_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = SensorReading(now - datetime.timedelta(0, 60 * 60), 15, 60)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'
