# This API has grown over time and is somewhat messy.  New additions using
# flask-restplus to help keep things in order, but the older parts of the code
# should probably also be migrated to restplus.

import datetime
import logging

from flask import Flask, jsonify, request, g
from flask_restx import Api, Resource, fields, marshal
from flask_login import LoginManager, current_user

import basicauth

from . import model
from . import auth
from .zones import a_device_state, api as zones_api
from .sensors import api as sensors_api
from .util import get_conf, get_db

from ..scheduler import SchedulerTemperaturePolicy


logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
api = Api(title="BoilerIO Heating Control",
          description="Partially migrated to restplus: some APIs are not "
                      "included here.")
api.add_namespace(zones_api, path='/zones')
api.add_namespace(sensors_api, path='/sensor')
api.init_app(app)
login_manager = LoginManager(app=app)


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()


# --------------------------------------------------------------------------
# Authorization

# Make login_required the default:
@app.before_request
def before_request():
    endpoint = app.view_functions.get(request.endpoint, None)
    if endpoint is None:
        # Authorized to view the 404
        return
    if current_user.is_authenticated:
        # Authorized:
        return
    # Not found:
    return login_manager.unauthorized()


@login_manager.request_loader
def load_user_from_request(request):
    """Authorize devices using HTTP basic auth."""
    auth_header = request.headers.get("Authorization")
    if auth_header is None:
        return None

    try:
        username, password = basicauth.decode(auth_header)
    except basicauth.DecodeError:
        return None

    # Usernames for devices are device IDs: integers
    try:
        username = int(username)
    except ValueError:
        return None

    # Check the username/password provided:
    db = get_db()
    try:
        endpoint = model.EndpointIdentity.get_device_by_id(db, username)
    except ValueError:
        return None

    hashed_password = auth.hash_password(password, endpoint.salt)
    if hashed_password.decode() == endpoint.device_secret_hashed:
        return auth.Device()
    return None


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
