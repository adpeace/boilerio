from .. import tempsensor
import mock

def test_callback_with_correct_temperature():
    LOCATOR = 'foo/sensor1'
    SENSOR_ID = 1
    msg = mock.MagicMock()
    msg.topic = LOCATOR
    msg.payload = '{"temperature": 12.5}'

    ts = tempsensor.EmonTHSensor(SENSOR_ID, LOCATOR)
    cb = mock.Mock()
    ts.add_callback(cb)

    # Simulate MQTT callback:
    ts._temp_callback(None, None, msg)

    cb.assert_called_with(ts)
    assert ts.temperature.reading == 12.5