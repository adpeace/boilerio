""" Interface to scheduler database. """

import psycopg2

def db_connect(host, db, user, pw):
    """ Connect to database

    Returns a postgres database connection created using the provided credentials.
    """
    connect_string = 'host={} dbname={} user={} password={}'.format(
        host, db, user, pw)
    conn = psycopg2.connect(connect_string)
    return conn

def update_last_state(db, when, state):
    """ Update cached state value. """
    cursor = db.cursor()
    cursor.execute('delete from state_cache;')
    cursor.execute('insert into state_cache '
                   '(state, updated) values (%s, %s);',
                   (state, when))

def get_last_state(db):
    """ Return cached temperature value. """
    cursor = db.cursor()
    cursor.execute('select state, updated from state_cache '
                   'limit 1;')
    results = cursor.fetchall()
    if len(results) == 1:
        r1 = results[0]
        return r1[0]
    else:
        return None

def update_last_temperature(db, when, temp, zone):
    """ Update cached temperature value. """
    cursor = db.cursor()
    cursor.execute('delete from temperature_cache where zone=%s;', (zone, ))
    cursor.execute('insert into temperature_cache '
                   '(temperature, updated, zone) values (%s, %s, %s);',
                   (temp, when, zone))

def get_cached_temperatures(db):
    """ Return cached temperature value. """
    cursor = db.cursor()
    cursor.execute('select temperature, updated, zone '
                   'from temperature_cache;')
    results = cursor.fetchall()
    return [TempReading(r[1], r[0], r[2]) for r in results]

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
    def delete_entry(cls, db, dow, time):
        """ Remove entries for all zones at a specified day/time.

        dow is the day of week, counting from 0 being Monday. """
        cursor = db.cursor()
        cursor.execute("delete from schedule where day=%s and starttime=%s",
                       (dow, time))

    @classmethod
    def from_db(cls, db):
        """ Create a schedule class instance from the database. """
        cursor = db.cursor()
        cursor.execute("select day, starttime, zone, temp from schedule "
                       "order by day, starttime, zone")
        entries = []
        for record in cursor:
            entries.append(record)
        return cls(entries)

class TempReading(object):
    """ Convenience class representing a temperature reading. """
    def __init__(self, when, temp, zone_id):
        self.when = when
        self.temp = temp
        self.zone_id = zone_id

class Zone(object):
    """A heating zone, with relay and temperature sensor."""
    def __init__(self, zone_id, name, boiler_relay, sensor):
        self.zone_id = zone_id
        self.name = name
        self.boiler_relay = boiler_relay
        self.sensor = sensor

    @classmethod
    def all_from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute("select zone_id, name, boiler_relay, sensor from zones")
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
    def from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute('select until, temp, zone from override')
        data = cursor.fetchall()
        return [cls(override[0], override[1], override[2])
                for override in data]

    @classmethod
    def clear_from_db(cls, connection):
        """ Cancel any current override in database. """
        cursor = connection.cursor()
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

