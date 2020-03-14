""" Interface to scheduler database. """

import psycopg2


def db_connect(host, db, user, pw):
    """ Connect to database

    Returns a postgres database connection created using the provided
    credentials.
    """
    connect_string = 'host={} dbname={} user={} password={}'.format(
        host, db, user, pw)
    conn = psycopg2.connect(connect_string)
    return conn


class FullSchedule(object):
    """ The heating schedule. """
    def __init__(self, entries):
        """Initialise a schedule representation.

        entries is a list of entries, of the form:
            [ (day of week, start time, zone, temperature target) ]

        day of week is zero-based (0 means Monday).  start time is a Python
        time object; zone is a zone ID referencing a valid zone.
        Temperature target is a temperature target in celcius.
        """
        self.entries = entries

    def __iter__(self):
        return self.entries.__iter__()

    @classmethod
    def create_entry(cls, db, dow, time, zone, temp):
        """ Create a schedule entry in the database.

        dow is the day of week, counting from 0 being Monday. """
        cursor = db.cursor()
        cursor.execute("insert into schedule (day, starttime, zone, temp) "
                       "values (%s, %s, %s, %s)", (dow, time, zone, temp))

    @classmethod
    def delete_entry(cls, db, dow, time, zone):
        """ Remove entries for all zones at a specified day/time.

        dow is the day of week, counting from 0 being Monday. """
        cursor = db.cursor()
        cursor.execute("delete from schedule where day=%s and starttime=%s "
                       "and zone=%s",
                       (dow, time, zone))

    @classmethod
    def from_db(cls, db, zone_id=None):
        """ Create a schedule class instance from the database. """
        cursor = db.cursor()
        if zone_id is None:
            cursor.execute("select day, starttime, zone, temp from schedule "
                           "order by day, starttime, zone")
        else:
            cursor.execute("select day, starttime, zone, temp from schedule "
                           "where zone=%s "
                           "order by day, starttime, zone", (zone_id,))
        entries = []
        for record in cursor:
            entries.append(record)
        return cls(entries)


class Zone(object):
    """A heating zone, with relay and temperature sensor."""
    def __init__(self, zone_id, name, boiler_relay, sensor_id):
        self.zone_id = zone_id
        self.name = name
        self.boiler_relay = boiler_relay
        self.sensor_id = sensor_id

    @classmethod
    def all_from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute("select zone_id, name, boiler_relay, sensor_id "
                       "from zones")
        zones = []
        for record in cursor:
            zone = Zone(record[0], record[1], record[2], record[3])
            zones.append(zone)
        return zones


class TargetOverride(object):
    """ Override the set temperature for a period of time. """
    def __init__(self, end, temp, zone):
        self.end = end
        self.temp = temp
        self.zone = zone

    @classmethod
    def from_db(cls, connection, zones=None):
        cursor = connection.cursor()
        cursor.execute('select until, temp, zone from override')
        data = cursor.fetchall()
        return [cls(override[0], override[1], override[2])
                for override in data
                if zones is None or override[2] in zones]

    @classmethod
    def clear_from_db(cls, connection, zone_id=None):
        """ Cancel any current override in database. """
        cursor = connection.cursor()
        if zone_id:
            cursor.execute('delete from override where zone=%s',
                           (zone_id, ))
        else:
            cursor.execute('delete from override')

    def to_dict(self):
        """Convert to a dictionary (for saving as JSON)."""
        return {
            'until': self.end.strftime("%Y-%m-%dT%H:%M"),
            'temp': self.temp,
            'zone': self.zone,
            }

    def save(self, connection):
        """ Replaces the current override in the database with this. """
        cursor = connection.cursor()
        cursor.execute('delete from override where zone=%s', (self.zone, ))
        cursor.execute('insert into override (until, temp, zone) '
                       'values (%s, %s, %s)',
                       (self.end, self.temp, self.zone))


class DeviceState(object):
    """The state reported by a device.

    Includes:
     - 'received' - the date/time in UTC the device report was received.
     - 'zone_id' - zone ID for the device.
     - 'target' - the target temperature the device is using.
     - 'current_temp' - the temperature the device currently sees (or None).
     - 'current_outside_temp' - the temperature the device currently sees for
                                outside (or None).
     - 'time_to_target' - time to a new target (or None).
     - 'dutycycle' - floating point value between 0 and 1.
    """
    def __init__(self, received, zone_id, state, target, current_temp,
                 time_to_target, current_outside_temp, dutycycle):
        self.received = received
        self.zone_id = zone_id
        self.state = state
        self.target = target
        self.current_temp = current_temp
        self.current_outside_temp = current_outside_temp
        self.time_to_target = time_to_target
        self.dutycycle = dutycycle

    def save(self, connection):
        cursor = connection.cursor()
        cursor.execute(
            'insert into device_reported_state '
            '(zone_id, received, state, target, current_temp, '
            'time_to_target, current_outside_temp, dutycycle) '
            'values (%s, %s, %s, %s, %s, %s, %s, %s)', (
                self.zone_id, self.received, self.state, self.target,
                self.current_temp, self.time_to_target,
                self.current_outside_temp, self.dutycycle,
            ))

    @classmethod
    def last_from_db(cls, connection, zone_id):
        cursor = connection.cursor()
        cursor.execute(
            'select received, state, target, current_temp, '
            'time_to_target, current_outside_temp, dutycycle '
            'from device_reported_state '
            'where zone_id=%s order by received desc limit 1', (zone_id,)
            )
        data = cursor.fetchall()
        if not data:
            return None
        data = data[0]
        return cls(data[0], zone_id, *data[1:])


class SensorReading(object):
    """Represents a single sensor reading.

    metric_type is one of 'temperature', 'humidity', 'battery_voltage'.
    """
    def __init__(self, sensor_id, when, metric_type, value):
        self.sensor_id = sensor_id
        self.when = when
        self.metric_type = metric_type
        self.value = value

    def save(self, connection):
        cursor = connection.cursor()
        cursor.execute("insert into sensor_reading "
                       "(sensor_id, metric_type, time, value) VALUES "
                       "(%s,%s,%s,%s)", (self.sensor_id, self.metric_type,
                                         self.when, self.value))


class Sensor(object):
    """A sensor, currently sensor."""
    def __init__(self, sensor_id, name, locator):
        self.sensor_id = sensor_id
        self.name = name
        self.locator = locator

    @classmethod
    def all_from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute("select sensor_id, name, locator from sensor")
        data = cursor.fetchall()
        return [cls(r[0], r[1], r[2]) for r in data]

    @classmethod
    def from_db(cls, connection, sensor_id):
        cursor = connection.cursor()
        cursor.execute("select name, locator from sensor "
                       "where sensor_id=%s", (sensor_id, ))
        data = cursor.fetchone()
        if not data:
            raise ValueError("No sensor found (%s)" % sensor_id)
        data = data[0]
        return cls(sensor_id, data[0], data[1])

    def get_last_readings(self, connection):
        """ Returns a list of the sensor's last readings.

        Includes one reading per metric_type published.
        """
        cursor = connection.cursor()
        cursor.execute("select metric_type, time, value from sensor_reading "
                       "where sensor_id=%s "
                       "order by time desc limit 1", (self.sensor_id, ))
        return [SensorReading(self.sensor_id, record[1], record[0], record[2])
                for record in cursor]


class TemperatureGradientMeasurement(object):
    """A record of a measured heating gradient."""
    def __init__(self, zone_id, when, delta, gradient):
        self.zone_id = zone_id
        self.when = when
        self.delta = delta
        self.gradient = gradient

    def save(self, connection):
        """Write gradient to database."""
        cursor = connection.cursor()
        cursor.execute(
            'insert into gradient_measurement '
            '(zone, "when", delta, gradient) values '
            '(%s, %s, %s, %s)',
            (self.zone_id, self.when, self.delta, self.gradient)
            )

    @staticmethod
    def get_gradient_table(connection, zone_id):
        """Return a list o list of temperature gradient averages.

        Returns a list of the form:
            [ (delta rounded to nearest 0.5, average gradient) ]
        """
        cursor = connection.cursor()
        cursor.execute(
            "select round(2 * cast(delta as numeric), 0) / 2 as d, "
            "avg(gradient), count(gradient) "
            "from gradient_measurement where zone=%s"
            "group by d order by d", (zone_id,)
            )
        return [{
            'delta': record[0],
            'gradient': record[1],
            'npoints': record[2]
            } for record in cursor]
