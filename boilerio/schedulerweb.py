# This API has grown over time and is somewhat messy.  New additions using
# flask-restplus to help keep things in order, but the older parts of the code
# should probably also be migrated to restplus.

import datetime
import logging

from flask import Flask, jsonify, request, g
from flask_restplus import Api, Resource, fields, marshal

from . import model
from .scheduler import SchedulerTemperaturePolicy
from .config import load_config

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
api = Api(app,
          description="Partially migrated to restplus: some APIs are not "
                      "included here.")

def get_conf():
    if not hasattr(g, 'conf'):
        g.conf = load_config()
    return g.conf

def get_db():
    conf = get_conf()
    if not hasattr(g, 'db'):
        g.db = model.db_connect(
            conf.get('heating', 'scheduler_db_host'),
            conf.get('heating', 'scheduler_db_name'),
            conf.get('heating', 'scheduler_db_user'),
            conf.get('heating', 'scheduler_db_password'))
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

# --------------------------------------------------------------------------

a_zone = api.model('Zone', {
    'zone_id': fields.Integer(description="ID of zone"),
    'name': fields.String(),
    'boiler_relay': fields.String(
        description="Identifier of boiler relay for this zone."),
    'sensor_id': fields.Integer(
        description="Identifier of sensor for this zone.."),
    })

an_override = api.model("Temperature target override", {
    'zone': fields.Integer(description="Which zone it applies to"),
    'end': fields.DateTime(description="Date/time the override ends"),
    'temp': fields.Float(description="Target temperature during override"),
    })

a_gradient_measurement = api.model('Temperature gradient', {
    'when': fields.DateTime(description="Date/time the measurement was taken."),
    'delta': fields.Float(description="Difference between inside and "
        "outside temperature at the start of the measurement."),
    'gradient': fields.Float(description="The temperature gradient in "
        "degrees C per hour."),
    })
a_gradient_average = api.model('Temperature gradient average', {
    'delta': fields.Float(description="Difference between inside and "
        "outside temperature"),
    'gradient': fields.Float(description="Average temperature gradient "
        "with heating on at temperature difference of delta."),
    'npoints': fields.Integer(description="Number of data points contributing "
        "to the average value given."),
    })

@api.route('/zones/<int:zone_id>/gradient_measurements')
class Gradient(Resource):
    @api.expect(a_gradient_measurement)
    def post(self, zone_id):
        tgm = model.TemperatureGradientMeasurement(
                zone_id, api.payload['when'], api.payload['delta'],
                api.payload['gradient'])
        db = get_db()
        tgm.save(db)
        db.commit()

@api.route('/zones/<int:zone_id>/gradients')
class GradientTable(Resource):
    @api.marshal_list_with(a_gradient_average)
    def get(self, zone_id):
        db = get_db()
        r = model.TemperatureGradientMeasurement.get_gradient_table(
                db, zone_id)
        return r

a_device_state = api.model('Device reported state', {
    'time_to_target': fields.Integer(description="Seconds until target reached."),
    'state': fields.String(description="State of device."),
    'target': fields.Float(description="Target the device is working towards."),
    'current_temp': fields.Float(description='Current temperature '
        'reported by the device.'),
    })

@api.route('/zones/<int:zone_id>/reported_state')
@api.param('zone_id', 'Zone ID for the time to target.')
class ReportedState(Resource):
    @api.expect(a_device_state)
    def post(self, zone_id):
        db = get_db()
        device_state = model.DeviceState(
                datetime.datetime.now(),
                zone_id, api.payload['state'], api.payload['target'],
                api.payload['current_temp'],
                api.payload['time_to_target'])
        device_state.save(db)
        db.commit()

    @api.marshal_with(a_device_state)
    def get(self, zone_id):
        db = get_db()
        device_state = model.DeviceState.from_db(db, zone_id)
        db.commit()
        return device_state

@api.route('/zones/<int:zone_id>/schedule')
@api.param('zone_id', 'Zone ID for the schedule.')
class ZoneSchedule(Resource):
    def get(self, zone_id):
        db = get_db()
        schedule = model.FullSchedule.from_db(db, zone_id)
        db.commit()

        entries = []
        for (dow, time, zone, temp) in schedule:
            entries.append({
                'day': dow,
                'time': time.strftime('%H:%M'),
                'temp': temp,
            })
        return entries

# --------------------------------------------------------------------------

def today_by_time_from_zones(today_by_zone):
    """Pivot a zone -> schedule dictionary to a list of (time, zone, temp).

    Returns a list of the form:
        [ (starttime, zones: [ {zone: zone, temp: temp} ]) ]
    given a dictionary of;
        { zone: [ (starttime, zone, temp) ] }
    """
    today_by_time = []
    # Nasty O(n^2), hwoever n and m are small (<5 and <10 respectively) so
    # going for something more readable here.
    for zone in today_by_zone:
        for tbz_entry in today_by_zone[zone]:
            tbz_when, tbz_zone, tbz_temp = tbz_entry
            inserted = False
            for tbt_entry in today_by_time:
                if tbt_entry['when'] == tbz_when:
                    tbt_entry['zones'].append({'zone': zone, 'temp': tbz_temp})
                    inserted = True
                    break
            if not inserted:
                today_by_time.append({
                    'when': tbz_when,
                    'zones': [{'zone': zone, 'temp': tbz_temp}],
                    })
    today_by_time.sort(key=lambda x: x['when'])
    # Map times to strings in returned value:
    return [{'when': entry['when'].strftime('%H:%M'), 'zones': entry['zones']}
            for entry in today_by_time]

@app.route("/summary")
def get_summary():
    now = datetime.datetime.now()
    db = get_db()

    schedule = model.FullSchedule.from_db(db)

    zones = model.Zone.all_from_db(db)
    zones_summary = sorted([{'zone_id': z.zone_id, 'name': z.name}
                            for z in zones],
                           key=lambda x: x['zone_id'])
    target_overrides = model.TargetOverride.from_db(db)

    scheduler = SchedulerTemperaturePolicy(
        schedule, target_overrides)

    for zone in zones_summary:
        zid = zone['zone_id']

        zone['target'] = scheduler.target(now, zid)
        reported_state = model.DeviceState.from_db(db, zid)
        zone['reported_state'] = marshal(reported_state, a_device_state)

        # We may have a stale override so check that the target is actually
        # being overriden:
        if scheduler.target_overridden(now, zid):
            zone_override = [zo for zo in target_overrides if zo.zone == zid]
            if len(zone_override) == 1:
                zone['target_override'] = zone_override[0].to_dict()
            else:
                zone['target_override'] = None
        else:
            zone['target_override'] = None

    today_by_zone = {z.zone_id: scheduler.get_day(now.weekday(), z.zone_id)
                     for z in zones}

    db.commit()
    result = {
        'zones': zones_summary,
        'server_day_of_week': now.weekday(),
        'today': today_by_time_from_zones(today_by_zone),
        }
    return jsonify(result)

def full_schedule_to_dict(full_schedule):
    """Generate a dictionary from a schedule object for conversion to JSON.

    Generate a dictionary like:
        { dow: [ {'when': start, 'temp':  {zone: temp}} ] }
    """
    json_schedule = {}
    for dow in range(7):
        json_schedule[dow] = []

    for entry in full_schedule:
        # Entries are ordered by dow, start, zone:
        entry_dow, entry_start, entry_zone, entry_temp = entry
        dow = json_schedule[entry_dow]
        entry_start_str = entry_start.strftime("%H:%M")
        added = False
        for e in dow:
            if e['when'] == entry_start_str:
                e['zones'].append({
                    'zone': entry_zone,
                    'temp': entry_temp
                    })
                added = True
                break
        if not added:
            dow.append({
                'when': entry_start.strftime('%H:%M'),
                'zones': [{'zone': entry_zone, 'temp': entry_temp}],
                })

    return json_schedule


#------------------------------------------------------------------------------
# Schedule.  This is a bit untidy/non-idiomatic.

@app.route("/schedule")
def get_schedule():
    db = get_db()
    full_schedule = model.FullSchedule.from_db(db)
    json_schedule = full_schedule_to_dict(full_schedule)
    tgt_override = [t.to_dict() for t in model.TargetOverride.from_db(db)]
    db.commit()
    return jsonify({
        'schedule': json_schedule,
        'target_override': tgt_override
        })

@app.route("/schedule/new_entry", methods=["POST"])
def add_schedule_entry():
    db = get_db()
    zones = model.Zone.all_from_db(db)
    try:
        time = datetime.datetime.strptime(request.values['time'], "%H:%M")
        time = time.time()
        day = int(request.values['day'])
        if not (day >= 0 and day < 7):
            raise ValueError("Day of week must be in range 0 to 7")
        temp = float(request.values['temp'])
        if not (temp >= 0 and temp < 35):
            raise ValueError("Target tempt must be in range 0 to 35")
        zone = int(request.values['zone'])
        if not any(z.zone_id == zone for z in zones):
            raise ValueError("Unknown zone %d" % zone)
    except ValueError:
        return ('', 400)
    model.FullSchedule.create_entry(db, day, time, zone, temp)
    db.commit()
    return ''

@app.route("/schedule/delete_entry", methods=["POST"])
def remove_schedule_entry():
    db = get_db()
    try:
        time = datetime.datetime.strptime(request.values['time'], "%H:%M")
        time = time.time()
        day = int(request.values['day'])
        zone = int(request.values['zone'])
        if not (day >= 0 and day < 7):
            raise ValueError("Day of week must be in range 0 to 7")
    except ValueError:
        return ('', 400)
    model.FullSchedule.delete_entry(db, day, time, zone)
    db.commit()
    return ''

# --------------------------------------------------------------------------
# Zones

@api.route("/zones")
class ListZones(Resource):
    @api.marshal_list_with(a_zone)
    def get(self):
        db = get_db()
        zones = model.Zone.all_from_db(db)
        return zones


@api.route("/zones/<int:zone_id>/override")
class Override(Resource):
    """Temperature override for a zone."""
    @api.response(code=200, model=an_override, description="OK")
    @api.response(code=204, description="No overrides active")
    def get(self, zone_id):
        """Get temperature override for zone.

        Returns no override if an override was in place but has expired."""
        # XXX we shouldn't be deciding on the server whether an override is
        # active since it doesn't tell us whether the device is implementing it
        # or not.  This should move to target/reported state model.
        now = datetime.datetime.now()
        db = get_db()
        overrides = model.TargetOverride.from_db(db, [zone_id])
        if not overrides:
            return None, 204

        assert len(overrides) == 1, "Only support one override per zone"
        override = overrides[0]
        if override.end > now:
            return marshal(override, an_override), 200
        return None, 204

    @api.doc(params={
        "temp": { 'description': "The override temperature to set.",
                  'type': float, 'required': True, 'in': 'formData' },
        "days": { "type": int, "in": "formData"},
        "hours": { "type": int, "in": "formData"},
        "mins": { "type": int, "in": "formData"},
    })
    def post(self, zone_id):
        """Configure a temperature override.

        Sepcify at least one of hours, mins, secs for duration."""
        try:
            secs = 0
            if 'days' in request.form:
                secs += int(request.form['days']) * 60 * 60 * 24
            if 'hours' in request.form:
                secs += int(request.form['hours']) * 60 * 60
            if 'mins' in request.form:
                secs += int(request.form['mins']) * 60
            if not secs:
                return 'Must specify days, hours, or mins (%s)' % str(dict(request.form)), 400

            duration = datetime.timedelta(0, secs)
            temp = float(request.form['temp'])
        except ValueError:
            return '', 400
        now = datetime.datetime.now()
        end = now + duration

        db = get_db()
        override = model.TargetOverride(end, temp, zone_id)
        override.save(db)
        db.commit()

        return ('', 200)

    def delete(self, zone_id):
        """Clear temperature override."""
        db = get_db()
        model.TargetOverride.clear_from_db(db, zone_id)
        db.commit()
        return '', 200


# --------------------------------------------------------------------------
# Sensors

a_sensor = api.model("Sensor", {
    'sensor_id': fields.Integer(description="Sensor ID"),
    'name': fields.String(description="Friendly name of sensor"),
    'locator': fields.String(
        description="How to find readings for the sensor locally.  This will "
        "be an MQTT topic to subscribe to.")
})


@api.route('/sensor')
class Sensors(Resource):
    """Set of known sensors."""
    @api.marshal_list_with(a_sensor)
    def get(self):
        db = get_db()
        return model.Sensor.all_from_db(db)


a_sensor_reading = api.model("Sensor reading", {
    'metric_type': fields.String(description="Metric type: "
                                 " temperature, humidity, or battery_voltage"),
    'when': fields.DateTime(description="When the reading occurred"),
    'value': fields.Float(description="The reading"),
})


@api.route('/sensor/<int:sensor_id>/readings')
class SensorReadings(Resource):
    @api.marshal_list_with(a_sensor_reading)
    def get(self, sensor_id):
        db = get_db()
        try:
            sensor = model.Sensor.from_db(db, sensor_id)
        except ValueError:
            return '', 404

        return sensor.get_last_readings(db)

    @api.expect(a_sensor_reading)
    def post(self, sensor_id):
        reading = model.SensorReading(
            int(sensor_id),
            datetime.datetime.strptime(api.payload['when'], '%Y-%m-%dT%H:%M:%S.%fZ'),
            api.payload['metric_type'],
            float(api.payload['value'])
            )
        db = get_db()
        reading.save(db)
        db.commit()