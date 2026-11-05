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
    now = 10000.0
    temp_reading = SensorReading(datetime.datetime.now(), 20, 60, now)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(15)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'

def test_start_on_if_below_temperature(thermostat, boiler, sensor):
    now = 10000.0
    temp_reading = SensorReading(datetime.datetime.now(), 15, 60, now)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'O'

def test_start_pwn_if_at_temperature(thermostat, boiler, sensor):
    now = 10000.0
    temp_reading = SensorReading(datetime.datetime.now(), 20, 60, now)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    # not ideal:
    assert thermostat._measurement_begin == now

def test_stale_temperature(thermostat, boiler, sensor):
    now = 10000.0
    temp_reading = SensorReading(datetime.datetime.now(), 15, 60, now - 3600)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'
