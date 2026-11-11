from datetime import datetime
from unittest.mock import MagicMock

import pytest

from .. import app, sensors


@pytest.fixture
def connection(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(sensors, 'get_db', lambda: connection)
    return connection


@pytest.fixture
def client():
    return app.create_app({'HEATING_TIMEZONE': 'Europe/London',
                           'LOGIN_DISABLED': True, 'SECRET_KEY': 'test'}).test_client()


def test_summary_includes_all_sensors_and_independent_metric_timestamps(client, connection):
    temperature_time = datetime.fromisoformat('2026-07-01T12:34:56.123456+01:00')
    humidity_time = datetime.fromisoformat('2026-07-01T11:30:00+00:00')
    connection.cursor.return_value.fetchall.return_value = [
        (1, 'Living room', 'temperature', temperature_time, 19.42),
        (1, 'Living room', 'humidity', humidity_time, 48),
        (2, 'Bedroom', 'temperature', temperature_time, 0),
        (2, 'Bedroom', None, None, None),
        (3, 'Kitchen', None, None, None),
        (3, 'Kitchen', None, None, None),
    ]

    response = client.get('/sensor/summary')

    assert response.status_code == 200
    assert response.json == [
        {'sensor_id': 1, 'name': 'Living room', 'state': {'battery': 'unknown'}, 'readings': {
            'temperature': {'value': 19.42, 'when': '2026-07-01T11:34:56.123456+00:00'},
            'humidity': {'value': 48.0, 'when': '2026-07-01T11:30:00+00:00'},
        }},
        {'sensor_id': 2, 'name': 'Bedroom', 'state': {'battery': 'unknown'}, 'readings': {
            'temperature': {'value': 0.0, 'when': '2026-07-01T11:34:56.123456+00:00'},
        }},
        {'sensor_id': 3, 'name': 'Kitchen', 'readings': {}, 'state': {'battery': 'unknown'}},
    ]
    connection.cursor.return_value.execute.assert_called_once()


def test_summary_without_sensors_is_an_empty_list(client, connection):
    connection.cursor.return_value.fetchall.return_value = []
    response = client.get('/sensor/summary')
    assert response.status_code == 200
    assert response.json == []


def test_summary_requires_authentication():
    client = app.create_app({'HEATING_TIMEZONE': 'UTC', 'SECRET_KEY': 'test'}).test_client()
    assert client.get('/sensor/summary').status_code == 401


def test_summary_uses_api_base_url_and_is_documented(connection):
    client = app.create_app({'HEATING_TIMEZONE': 'UTC', 'LOGIN_DISABLED': True,
                            'BASE_URL': '/api'}).test_client()
    connection.cursor.return_value.fetchall.return_value = []
    assert client.get('/api/sensor/summary').json == []
    assert client.get('/sensor/summary').status_code == 404
    schema = client.get('/api/swagger.json').json
    assert '/sensor/summary' in schema['paths']


def test_existing_sensor_list_and_reading_endpoints_keep_their_shapes(client, connection):
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [(1, 'Living room', 'emonth/1', 2)]
    assert client.get('/sensor/').json == [
        {'sensor_id': 1, 'name': 'Living room', 'locator': 'emonth/1'},
    ]

    when = datetime.fromisoformat('2026-07-01T11:30:00+00:00')
    cursor.fetchone.side_effect = [
        ('Living room', 'emonth/1', 2),
        ('temperature', when, 19.42),
        ('humidity', when, 48),
        None,
    ]
    assert client.get('/sensor/1/readings').json == [
        {'metric_type': 'temperature', 'when': when.isoformat(), 'value': 19.42},
        {'metric_type': 'humidity', 'when': when.isoformat(), 'value': 48.0},
    ]

    cursor.fetchone.side_effect = None
    cursor.fetchone.return_value = None
    assert client.get('/sensor/99/readings').status_code == 404


@pytest.mark.parametrize('voltage,age,status', [
    (1.2, 0, 'low'), (2.0, 0, 'low'), (2.01, 0, 'ok'), (2.5, 0, 'ok'),
    (1.2, 1800, 'low'), (1.2, 1800.001, 'unknown'), (2.5, 1801, 'unknown'),
    (None, 0, 'unknown'), (float('nan'), 0, 'unknown'), (-1, 0, 'unknown'),
])
def test_summary_battery_state_and_raw_voltage(client, connection, monkeypatch, voltage, age, status):
    now = datetime.fromisoformat('2026-07-01T12:00:00+00:00')
    clock = MagicMock(wraps=sensors.datetime)
    clock.datetime.now.return_value = now
    monkeypatch.setattr(sensors, 'datetime', clock)
    when = now - sensors.datetime.timedelta(seconds=age)
    connection.cursor.return_value.fetchall.return_value = [
        (5, 'Living room', 'battery_voltage', when, voltage),
    ]
    response = client.get('/sensor/summary')
    assert response.status_code == 200
    assert response.json[0]['state'] == {'battery': status}
    if voltage is None or voltage != voltage or voltage < 0:
        assert response.json[0]['readings'] == {}
    else:
        assert response.json[0]['readings']['battery_voltage'] == {'when': when.isoformat(), 'value': voltage}


@pytest.mark.parametrize('voltage', [-1, 'nan', 'inf', None, 'bad'])
def test_api_rejects_invalid_battery_voltage(client, connection, voltage):
    response = client.post('/sensor/5/readings', json={
        'metric_type': 'battery_voltage', 'when': '2026-07-01T12:00:00+00:00', 'value': voltage,
    }, headers={'X-Requested-With': 'test'})
    assert response.status_code == 400
    connection.cursor.return_value.execute.assert_not_called()


def test_api_accepts_battery_voltage_and_latest_readings_include_it(client, connection):
    when = datetime.fromisoformat('2026-07-01T12:00:00+00:00')
    response = client.post('/sensor/5/readings', json={
        'metric_type': 'battery_voltage', 'when': when.isoformat(), 'value': 1.2,
    }, headers={'X-Requested-With': 'test'})
    assert response.status_code == 200
    assert connection.cursor.return_value.execute.call_args.args[1] == (5, 'battery_voltage', when, 1.2)
    connection.commit.assert_called_once()

    connection.cursor.return_value.fetchone.side_effect = [
        ('Living room', 'emonth/5', 1), None, None, ('battery_voltage', when, 1.2),
    ]
    assert client.get('/sensor/5/readings').json == [
        {'metric_type': 'battery_voltage', 'when': when.isoformat(), 'value': 1.2},
    ]
