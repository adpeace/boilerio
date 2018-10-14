import datetime
import pytest
from boilerio.thermostat import Thermostat, TempReading

class FakeBoiler(object):
    def __init__(self):
        self.last_command = None

    def on(self):
        self.last_command = 'O'

    def off(self):
        self.last_command = 'X'

@pytest.yield_fixture
def boiler():
    yield FakeBoiler()

@pytest.yield_fixture
def thermostat(boiler):
    yield Thermostat(boiler)

def test_start_off_if_above_temperature(thermostat, boiler):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 20)
    thermostat.set_target_temperature(15)
    thermostat.update_temperature(temp_reading)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'

def test_start_on_if_below_temperature(thermostat, boiler):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 15)
    thermostat.set_target_temperature(20)
    thermostat.update_temperature(temp_reading)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'O'

def test_start_pwn_if_at_temperature(thermostat, boiler):
    now = datetime.datetime.now()
    temp_reading = TempReading(now, 20)
    thermostat.set_target_temperature(20)
    thermostat.update_temperature(temp_reading)
    thermostat.interval_elapsed(now)
    # not ideal:
    assert thermostat._measurement_begin == now

def test_stale_temperature(thermostat, boiler):
    now = datetime.datetime.now()
    temp_reading = TempReading(now - datetime.timedelta(0, 60 * 60), 15)
    thermostat.set_target_temperature(20)
    thermostat.update_temperature(temp_reading)
    thermostat.interval_elapsed(now)
    assert boiler.last_command == 'X'
