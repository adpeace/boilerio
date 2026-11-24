import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from .. import model


def test_installation_id_is_a_lowercase_string():
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = (
        uuid.UUID('0B7C6F4E-5D3A-4C1B-9E8F-2A1D0C9B8A7F'),)
    assert model.installation_id(conn) == '0b7c6f4e-5d3a-4c1b-9e8f-2a1d0c9b8a7f'
    conn.cursor.return_value.execute.assert_called_once_with(
        'select installation_id from installation')
    conn.commit.assert_not_called()


def test_installation_id_is_created_on_first_use():
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.side_effect = [None, ('0b7c6f4e-5d3a-4c1b-9e8f-2a1d0c9b8a7f',)]
    assert model.installation_id(conn) == '0b7c6f4e-5d3a-4c1b-9e8f-2a1d0c9b8a7f'
    assert [c.args[0] for c in cursor.execute.call_args_list] == [
        'select installation_id from installation',
        'insert into installation default values on conflict do nothing',
        'select installation_id from installation',
    ]
    conn.commit.assert_called_once()


def test_installation_id_still_missing_after_insert_raises():
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = None
    with pytest.raises(LookupError):
        model.installation_id(conn)


def test_missing_installation_table_says_the_schema_is_out_of_date():
    class UndefinedTable(Exception):
        pgcode = '42P01'

    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = UndefinedTable()
    with pytest.raises(RuntimeError, match='schema is older'):
        model.installation_id(conn)
    conn.rollback.assert_called_once()


def test_other_database_errors_propagate_unchanged():
    class Other(Exception):
        pgcode = '42501'

    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = Other()
    with pytest.raises(Other):
        model.installation_id(conn)
    conn.rollback.assert_not_called()


def test_sensor_from_db_missing_raises():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with pytest.raises(ValueError):
        model.Sensor.from_db(conn, 99)


@pytest.mark.parametrize('construct,attribute', [
    (lambda when: model.TargetOverride(when, 20, 1), 'end'),
    (lambda when: model.ControllerState(when, 1, 'heating', 20, 18, None, 10, 1), 'received'),
    (lambda when: model.SensorReading(1, when, 'temperature', 20), 'when'),
    (lambda when: model.TemperatureGradientMeasurement(1, when, 10, 2), 'when'),
])
def test_models_normalize_offsets_and_reject_naive_timestamps(construct, attribute):
    when = datetime.fromisoformat('2026-07-01T12:34:56.123456+01:00')
    normalized = getattr(construct(when), attribute)
    assert normalized == when
    assert normalized.utcoffset() == timedelta(0)
    assert normalized.hour == 11
    assert normalized.microsecond == 123456
    with pytest.raises(ValueError):
        construct(when.replace(tzinfo=None))


def test_never_infer_timezone_for_a_naive_datetime():
    with pytest.raises(ValueError):
        model.as_utc(datetime(2026, 7, 1))


@pytest.mark.parametrize('zone_id', [0, 1, -1])
def test_clear_override_only_deletes_the_requested_zone(zone_id):
    conn = MagicMock()
    model.TargetOverride.clear_from_db(conn, zone_id)
    conn.cursor.return_value.execute.assert_called_once_with(
        'delete from override where zone=%s', (zone_id,))


def test_clear_all_overrides_requires_no_zone_id():
    conn = MagicMock()
    model.TargetOverride.clear_from_db(conn)
    conn.cursor.return_value.execute.assert_called_once_with('delete from override')
