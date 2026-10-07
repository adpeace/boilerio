import sys
from unittest.mock import MagicMock

import pytest

from .. import boiler_to_mqtt


def test_run_opens_passed_device_path(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(boiler_to_mqtt.mqtt, 'Client', lambda *args, **kwargs: client)
    monkeypatch.setattr(sys, 'argv', ['boiler_to_mqtt', '/dev/wrong-device'])

    class StopBeforeSerialLoop(Exception):
        pass

    def open_serial(path, baudrate, timeout):
        assert (path, baudrate, timeout) == ('/dev/ttyUSB0', 57600, 0.5)
        raise StopBeforeSerialLoop

    monkeypatch.setattr(boiler_to_mqtt.serial, 'Serial', open_serial)

    with pytest.raises(StopBeforeSerialLoop):
        boiler_to_mqtt.run('mqtt.local', 'user', 'password', 'heating/info',
                           'heating/demand', '/dev/ttyUSB0')
    client.loop_stop.assert_called_once()
