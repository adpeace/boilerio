import sys
from unittest.mock import MagicMock

import pytest

from .. import danfoss_bridge


def deliver(payload, topic='heating/demand'):
    userdata = {'demand_topic': 'heating/demand', 'command_queue': []}
    msg = MagicMock(topic=topic, payload=payload)
    danfoss_bridge.on_message(None, userdata, msg)
    return userdata['command_queue']


@pytest.mark.parametrize('command', ['O', 'X', 'L'])
def test_on_message_queues_valid_commands(command):
    payload = b'{"command": "%s", "thermostat": "0xBAB1"}' % command.encode()
    assert deliver(payload) == [{'command': command, 'thermostat': '0xbab1'}]


@pytest.mark.parametrize('payload', [
    b'{"command": "O", "thermostat": 47793}',     # unquoted ID: TypeError
    b'{"command": "O"}',                          # missing ID: KeyError
    b'{"command": "O", "thermostat": "nonsense"}',
    b'["O", "0xbab1"]',                           # not an object
    b'not json',
    b'{"command": "Z", "thermostat": "0xbab1"}',  # unknown command
    b'{"thermostat": "0xbab1"}',                  # missing command
])
def test_on_message_rejects_bad_requests_without_raising(payload):
    assert deliver(payload) == []


def test_on_message_ignores_other_topics():
    assert deliver(b'{"command": "O", "thermostat": "0xbab1"}', topic='other') == []


def test_run_opens_passed_device_path(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(danfoss_bridge.mqtt, 'Client', lambda *args, **kwargs: client)
    monkeypatch.setattr(sys, 'argv', ['boilerio-danfoss-bridge', '/dev/wrong-device'])

    class StopBeforeSerialLoop(Exception):
        pass

    def open_serial(path, baudrate, timeout):
        assert (path, baudrate, timeout) == ('/dev/ttyUSB0', 57600, 0.5)
        raise StopBeforeSerialLoop

    monkeypatch.setattr(danfoss_bridge.serial, 'Serial', open_serial)

    with pytest.raises(StopBeforeSerialLoop):
        danfoss_bridge.run('mqtt.local', 'user', 'password', 'heating/info',
                           'heating/demand', '/dev/ttyUSB0')
    client.loop_stop.assert_called_once()
