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

def update_last_temperature(db, when, temp):
    """ Update cached temperature value. """
    cursor = db.cursor()
    cursor.execute('delete from temperature_cache;')
    cursor.execute('insert into temperature_cache '
                   '(temperature, updated) values (%s, %s);',
                   (temp, when))

def get_last_temperature(db):
    """ Return cached temperature value. """
    cursor = db.cursor()
    cursor.execute('select temperature, updated from temperature_cache '
                   'limit 1;')
    results = cursor.fetchall()
    if len(results) == 1:
        r1 = results[0]
        return TempReading(r1[1], r1[0])
    else:
        return None

class FullSchedule(object):
    """ The heating schedule. """
    def __init__(self, entries):
        self.entries = entries

    def __iter__(self):
        return self.entries.__iter__()

    @classmethod
    def create_entry(cls, db, dow, time, temp):
        """ Create a schedule entry in the database.

        dow is the day of week, counting from 0 being Monday. """
        cursor = db.cursor()
        cursor.execute("insert into schedule (day, starttime, temp) "
                       "values (%s, %s, %s)", (dow, time, temp))

    @classmethod
    def delete_entry(cls, db, dow, time):
        """ Remove an entry form the databse.

        dow is the day of week, counting from 0 being Monday. """
        cursor = db.cursor()
        cursor.execute("delete from schedule where day=%s and starttime=%s",
                       (dow, time))

    @classmethod
    def from_db(cls, db):
        """ Create a schedule class instance from the database. """
        cursor = db.cursor()
        cursor.execute("select day, starttime, temp from schedule "
                       "order by day, starttime")
        entries = []
        for record in cursor:
            entries.append(record)
        return cls(entries)

class TempReading(object):
    """ Convenience class representing a temperature reading. """
    def __init__(self, when, temp):
        self.when = when
        self.temp = temp

class TargetOverride(object):
    """ Override the set temperature for a period of time. """
    def __init__(self, end, temp):
        self.end = end
        self.temp = temp

    @classmethod
    def from_db(cls, connection):
        cursor = connection.cursor()
        cursor.execute('select until, temp from override limit 1')
        data = cursor.fetchone()
        if not data:
            return None
        until, temp = data
        return cls(until, temp)

    @classmethod
    def clear_from_db(cls, connection):
        """ Cancel any current override in database. """
        cursor = connection.cursor()
        cursor.execute('delete from override')

    def save(self, connection):
        """ Replaces the current override in the database with this. """
        cursor = connection.cursor()
        cursor.execute('delete from override')
        cursor.execute('insert into override (until, temp) '
                       'values (%s, %s)',
                       (self.end, self.temp))

