# This API has grown over time and is somewhat messy.  New additions using
# flask-restplus to help keep things in order, but the older parts of the code
# should probably also be migrated to restplus.

import datetime
import logging

from flask import Flask, jsonify, request, g
from flask_restx import Api, Resource, fields, marshal

from . import model
from . import schedulerweb_zones
from .scheduler import SchedulerTemperaturePolicy
from .schedulerweb_util import get_conf, get_db


logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
api = Api(title="BoilerIO Heating Control",
          description="Partially migrated to restplus: some APIs are not "
                      "included here.")
api.add_namespace(schedulerweb_zones.api, path='/zones')
api.init_app(app)

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

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
            tbz_when, _, tbz_temp = tbz_entry
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
        reported_state = model.DeviceState.last_from_db(db, zid)
        zone['reported_state'] = marshal(reported_state, schedulerweb_zones.a_device_state)

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