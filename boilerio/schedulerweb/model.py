""" Interface to scheduler database. """

import psycopg2
import base64
import datetime


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
    def __init__(self, entries: list[tuple]):
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
    def __init__(self, end: datetime.datetime, temp: float, zone: int):
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


SENSOR_METRIC_TYPES = ['temperature', 'humidity']


class SensorReading(object):
    """Represents a single sensor reading.

    metric_type is one of 'temperature', 'humidity'.
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
    def __init__(self, sensor_id: int, name: str, locator: str, zone_id: int):
        self.sensor_id = sensor_id
        self.name = name
        self.locator = locator
        self.zone_id = zone_id

    @classmethod
    def all_from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute("select sensor_id, name, locator, zone from sensor")
        data = cursor.fetchall()
        return [cls(r[0], r[1], r[2], r[3]) for r in data]

    @classmethod
    def from_db(cls, connection, sensor_id):
        cursor = connection.cursor()
        cursor.execute("select name, locator, zone from sensor "
                       "where sensor_id=%s", (sensor_id, ))
        data = cursor.fetchone()
        if not data:
            raise ValueError("No sensor found (%s)" % sensor_id)
        data = data[0]
        return cls(sensor_id, data[0], data[1], data[2])

    def get_last_readings(self, connection) -> list[SensorReading]:
        """Returns a list of the sensor's last readings.

        Includes one reading per metric_type published.
        """
        readings = []
        cursor = connection.cursor()
        for metric_type in SENSOR_METRIC_TYPES:
            cursor.execute("select metric_type, time, value from sensor_reading "
                        "where sensor_id=%s and metric_type=%s"
                        "order by time desc limit 1", (self.sensor_id, metric_type))
            row = cursor.fetchone()
            if row:  # Only create reading if we found one
                readings.append(SensorReading(self.sensor_id, row[1], metric_type, row[2]))
        return readings


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


class EndpointIdentity(object):
    """Authentication information stored for endpoints in a home.

    Valid crednetials authorize their user to access the API.
    """

    def __init__(self, device_id, device_secret_hashed, salt):
        self.device_id = device_id
        self.device_secret_hashed = device_secret_hashed
        self.salt = salt

    @classmethod
    def get_device_by_id(cls, connection, device_id):
        """Returns a device object given a device identifier.

        This includes the hashed secret and salt for that device."""
        cursor = connection.cursor()
        cursor.execute(
            "select device_id, device_secret_hashed, salt "
            "from device where device_id=%s", (device_id,)
        )
        if cursor.rowcount != 1:
            raise ValueError("Device not found")
        else:
            device_id, device_secret_hashed, salt = cursor.fetchone()
            salt = base64.b64decode(salt)
            return cls(device_id, device_secret_hashed, salt)


def client_secret_is_valid(db, secret):
    cursor = db.cursor()
    cursor.execute('select * from clientsecrets where secret=%s', (secret,))
    return cursor.rowcount == 1


class UserIdentity:
    def __init__(self, user_id, google_subscriber_id, name, email, picture):
        self.user_id = user_id
        self.google_subscriber_id = google_subscriber_id
        self.name = name
        self.email = email
        self.picture = picture

    def update(self, db, name, email, picture):
        self.name = name
        self.email = email
        self.picture = picture

        cursor = db.cursor()
        cursor.execute(
            "update users set name=%s, email=%s, picture=%s "
            "where user_id=%s", (self.name, self.email, self.picture, self.user_id)
        )
        # Check 1 user updated
        if cursor.rowcount != 1:
            raise ValueError("Failed to update 1 user (%d)" % cursor.rowcount)

    @classmethod
    def lookup_user_by_google_id(cls, db, google_subscriber_id):
        cursor = db.cursor()
        cursor.execute(
            "select user_id, google_subscriber_id, name, email, picture from users "
            "where google_subscriber_id=%s", (google_subscriber_id,))
        if cursor.rowcount != 1:
            return None
        return cls(*cursor.fetchone())

    @classmethod
    def lookup_user_by_internal_id(cls, db, user_id):
        cursor = db.cursor()
        cursor.execute(
            "select user_id, google_subscriber_id, name, email, picture from users "
            "where user_id=%s", (user_id,))
        if cursor.rowcount != 1:
            return None
        return cls(*cursor.fetchone())
