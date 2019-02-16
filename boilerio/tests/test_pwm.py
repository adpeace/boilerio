import mock
from datetime import datetime, timedelta
from boilerio import pwm

def test_start_off():
    mock_device = mock.MagicMock()
    c = pwm.PWM(0, timedelta(0, 600), mock_device)
    now = datetime.now()
    c.update(now)
    mock_device.off.assert_called()
    mock_device.on.assert_not_called()

def test_start_on():
    mock_device = mock.MagicMock()
    c = pwm.PWM(0.5, timedelta(0, 600), mock_device)
    now = datetime.now()
    c.update(now)
    mock_device.off.assert_not_called()
    mock_device.on.assert_called()

def test_device_modulated():
    mock_device = mock.MagicMock()
    period = timedelta(0,600)
    off_before = timedelta(0,301)
    c = pwm.PWM(0.5, timedelta(0, 600), mock_device)

    now = datetime.now()
    c.update(now)
    mock_device.off.assert_not_called()
    mock_device.on.assert_called()

    now += off_before
    c.update(now)
    mock_device.off.assert_called()
