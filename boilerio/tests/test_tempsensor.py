"""Tests for the tempsensor module."""

from .. import tempsensor
import mock


LOCATOR = 'foo/sensor1'
SENSOR_ID = 1


def test_callback_with_correct_temperature():
    # Given
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.Mock()
    ts.add_callback(cb)

    # When: Simulate MQTT callback:
    ts._temp_callback(None, None, msg)

    # Then:
    cb.assert_called_with(ts)
    assert ts.temperature.reading == 12.5


def test_failed_callback_doesnt_cause_leaked_exception():
    # Given
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5}'

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
    msg.payload = '{"temperature": 12.5}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.MagicMock(side_effect=RuntimeError())
    cb2 = mock.MagicMock(side_effect=RuntimeError())
    ts.add_callback(cb)
    ts.add_callback(cb2)

    # When/Then: simulate MQTT callback - this should not raise:
    ts._temp_callback(None, None, msg)

    cb.assert_called_once()
    cb2.assert_called_once()