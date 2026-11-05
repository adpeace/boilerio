from boilerio import monitor
from boilerio.schedulerweb.model import Zone
from boilerio.tempsensor import EmonTHSensor
from configparser import RawConfigParser
from types import SimpleNamespace
from unittest.mock import Mock

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


def test_main_reaches_mqtt_loop_with_zone_sensor_id(monkeypatch):
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
    mqtt.loop_forever.side_effect = lambda: mqtt.on_connect(
        mqtt, None, None, SimpleNamespace(is_failure=False), None)

    monitor.main()

    mqtt.loop_forever.assert_called_once()
