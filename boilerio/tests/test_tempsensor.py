"""Tests for the tempsensor module."""

from .. import tempsensor
from unittest import mock
import json
import pytest


LOCATOR = 'foo/sensor1'
SENSOR_ID = 1


def test_callback_with_correct_temperature():
    # Given
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5, "humidity": 60.0}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.Mock()
    ts.add_callback(cb)

    # When: Simulate MQTT callback:
    ts._temp_callback(None, None, msg)

    # Then:
    cb.assert_called_with(ts)
    assert ts.reading.temperature == 12.5
    assert ts.reading.relative_humidity == 60.0


def test_failed_callback_doesnt_cause_leaked_exception():
    # Given
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5, "humidity": 60.0}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.MagicMock(side_effect=RuntimeError())
    ts.add_callback(cb)

    # When/Then: simulate MQTT callback - this should not raise:
    ts._temp_callback(None, None, msg)

    cb.assert_called_with(ts)


def test_all_callbacks_run_even_if_one_fails():
    # Given
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5, "humidity": 60.0}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.MagicMock(side_effect=RuntimeError())
    cb2 = mock.MagicMock(side_effect=RuntimeError())
    ts.add_callback(cb)
    ts.add_callback(cb2)

    # When/Then: simulate MQTT callback - this should not raise:
    ts._temp_callback(None, None, msg)

    cb.assert_called_once()
    cb2.assert_called_once()


def test_one_callback_delivers_all_values_even_when_unchanged():
    sensor = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    readings = []
    sensor.add_callback(lambda s: readings.append(s.reading))
    msg = mock.Mock(topic=LOCATOR, payload=json.dumps({
        'temperature': '17.96', 'humidity': '61.9', 'battery': '2.5',
    }))

    sensor._temp_callback(None, None, msg)
    sensor._temp_callback(None, None, msg)

    assert len(readings) == 2
    assert readings[0] is not readings[1]
    for reading in readings:
        assert reading.temperature == 17.96
        assert reading.relative_humidity == 61.9
        assert reading.battery_voltage == 2.5
        assert reading.when.utcoffset().total_seconds() == 0


@pytest.mark.parametrize('battery', [None, '', 'bad', 'nan', 'inf', '-1', {}])
def test_invalid_battery_does_not_discard_temperature(battery):
    sensor = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    callback = mock.Mock()
    sensor.add_callback(callback)
    msg = mock.Mock(topic=LOCATOR, payload=json.dumps({
        'temperature': '18.59', 'humidity': '67.8', 'battery': battery,
    }))

    sensor._temp_callback(None, None, msg)

    assert sensor.reading.temperature == 18.59
    assert sensor.reading.battery_voltage is None
    callback.assert_called_once_with(sensor)


def test_missing_battery_is_not_copied_from_the_previous_report():
    sensor = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    callback = mock.Mock()
    sensor.add_callback(callback)
    sensor._temp_callback(None, None, mock.Mock(topic=LOCATOR, payload=json.dumps({
        'temperature': '18.59', 'humidity': '67.8', 'battery': '2.5',
    })))
    assert sensor.reading.battery_voltage == 2.5

    sensor._temp_callback(None, None, mock.Mock(topic=LOCATOR, payload=json.dumps({
        'temperature': '19', 'humidity': '67.8',
    })))
    assert sensor.reading.battery_voltage is None
    assert callback.call_count == 2


def test_malformed_or_unrelated_messages_do_not_publish_previous_readings():
    sensor = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    callback = mock.Mock()
    sensor.add_callback(callback)
    sensor._temp_callback(None, None, mock.Mock(topic=LOCATOR,
                                              payload='{"temperature": 18.59, "humidity": 67.8, "battery": 1.2}'))
    previous = sensor.reading
    callback.reset_mock()
    for msg in [mock.Mock(topic='unrelated', payload='{"battery": "1.2"}'),
                mock.Mock(topic=LOCATOR, payload='bad json'),
                mock.Mock(topic=LOCATOR, payload='{"temperature": "bad"}'),
                mock.Mock(topic=LOCATOR, payload='{"battery": "1.2"}')]:
        sensor._temp_callback(None, None, msg)
    assert sensor.reading is previous
    callback.assert_not_called()
