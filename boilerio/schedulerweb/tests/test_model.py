from unittest.mock import MagicMock

import pytest

from .. import model


def _stub_connection(fetchone_result):
    """A connection whose cursor returns the given row from fetchone()."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_result
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return connection


def test_sensor_from_db_maps_columns():
    # Row is (name, locator, zone); sensor_id comes from the lookup argument.
    conn = _stub_connection(("Living room", "emonth/1", 2))
    sensor = model.Sensor.from_db(conn, 7)
    assert sensor.sensor_id == 7
    assert sensor.name == "Living room"
    assert sensor.locator == "emonth/1"
    assert sensor.zone_id == 2


def test_sensor_from_db_missing_raises():
    conn = _stub_connection(None)
    with pytest.raises(ValueError):
        model.Sensor.from_db(conn, 99)
