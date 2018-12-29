from datetime import datetime, timedelta
from boilerio import monitor

def test_none_to_on_transition_no_reading():
    """Test that when the boiler turns on for the first time that
    a temperature reading provided shortly afterwards doesn't cause
    a gradient to be generated."""
    m = monitor.Monitor()
    t = datetime(2010, 1, 1, 0, 0)
    m.set_outside_temperature(10, t)
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)
    assert m.temperature_update(22, t + timedelta(seconds=10)) == None

def test_first_ten_minutes_are_ignored():
    """Check that warmup period is ignored."""
    m = monitor.Monitor(warmup_interval_s=60)
    t = datetime(2010, 1, 1, 0, 0)
    m.set_outside_temperature(10, t)
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)
    assert m.temperature_update(21, t + timedelta(seconds=120)) == None
    assert m.temperature_update(23, t + timedelta(seconds=1320)) == (11, 6.0)

def test_boiler_already_on():
    """Check that multiple boiler on messages don't cause a problem."""
    m = monitor.Monitor(warmup_interval_s=60)
    t = datetime(2010, 1, 1, 0, 0)
    m.set_outside_temperature(10, t)

    # First update should not capture temperature because the boiler isn't on long enough
    assert m.temperature_update(20, t) == None
    m.boiler_on(t)

    # Next update should be captured:
    m.boiler_on(t + timedelta(seconds=119))
    assert m.temperature_update(21, t + timedelta(seconds=120)) == None

    # Final update should produce a result:
    m.boiler_on(t + timedelta(seconds=1319))
    assert m.temperature_update(23, t + timedelta(seconds=1320)) == (11, 6.0)
