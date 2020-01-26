import datetime
import pytest
from ..thermostat import Thermostat
from ..tempsensor import TempReading

class FakeBoiler(object):
    def __init__(self):
        self.last_command = None

    def on(self):
        self.last_command = 'O'

    def off(self):
        self.last_command = 'X'

class MockSensor(object):
    def __init__(self):
        self.temperature = None

    def set_temp(self, temp):
        self.temperature = temp

@pytest.yield_fixture
def sensor():
    yield MockSensor()

@pytest.yield_fixture
def boiler():
    yield FakeBoiler()

@pytest.yield_fixture
def thermostat(boiler, sensor):
    yield Thermostat(boiler, sensor)

def test_start_off_if_above_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 20)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(15)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'

def test_start_on_if_below_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 15)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'O'

def test_start_pwn_if_at_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 20)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    # not ideal:
    assert thermostat._measurement_begin == now

def test_stale_temperature(thermostat, boiler, sensor):
    now = datetime.datetime.now()
    temp_reading = TempReading(now - datetime.timedelta(0, 60 * 60), 15)
    sensor.set_temp(temp_reading)
    thermostat.set_target_temperature(20)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'
