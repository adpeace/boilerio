import maintaintemp
import pytest
import datetime

class FakeBoiler(maintaintemp.BoilerControl):
    def __init__(self, thermostat_id):
        super(FakeBoiler, self).__init__(thermostat_id)
        self.last_command = None

    def command(self, cmd):
        self.last_command = cmd

@pytest.yield_fixture
def boiler():
    yield FakeBoiler(0)

@pytest.yield_fixture
def state(boiler):
    state = maintaintemp.State(boiler)
    yield state

def test_start_off_if_above_temperature(state, boiler):
    state.now = datetime.datetime.now()
    state.update_target_temperature(15)
    state.update_temperature(20)
    maintaintemp.period(state)
    assert boiler.last_command == 'X'

def test_start_on_if_below_temperature(state, boiler):
    state.now = datetime.datetime.now()
    state.update_target_temperature(20)
    state.update_temperature(15)
    maintaintemp.period(state)
    assert boiler.last_command == 'O'

def test_start_pwn_if_at_temperature(state, boiler):
    state.now = datetime.datetime.now()
    state.update_target_temperature(20)
    state.update_temperature(20)
    maintaintemp.period(state)
    # not ideal:
    assert state.state == maintaintemp.MODE_PWM

def test_stale_temperature(state, boiler):
    now = datetime.datetime.now()
    state.now = now - datetime.timedelta(0, 60 * 60)
    state.update_target_temperature(20)
    state.update_temperature(20)
    state.now = now
    maintaintemp.period(state)
    assert boiler.last_command == 'X'
    assert state.state == maintaintemp.MODE_STALE
