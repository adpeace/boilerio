#!/usr/bin/env python

import datetime
from flask import Flask, jsonify, request, g

import model
from scheduler import SchedulerTemperaturePolicy
from config import load_config

app = Flask(__name__)

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
    today_by_time.sort(cmp=lambda x,y: cmp(x['when'], y['when']))
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
                           cmp=lambda x, y: cmp(x['zone_id'], y['zone_id']))
    target_overrides = model.TargetOverride.from_db(db)
    current_temps = model.get_cached_temperatures(db)

    scheduler = SchedulerTemperaturePolicy(
        schedule, target_overrides)

    for zone in zones_summary:
        zid = zone['zone_id']

        zone['target'] = scheduler.target(now, zid)
        
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

        zone_temp = [zt for zt in current_temps if zt.zone_id == zid]
        if len(zone_temp) == 1:
            zone['current_temp'] = zone_temp[0].temp
        else:
            zone['current_temp'] = None

    today_by_zone = {z.zone_id: scheduler.get_day(now.weekday(), z.zone_id)
                     for z in zones}
        
    db.commit()
    result = {
        'zones': zones_summary,
        'server_day_of_week': now.weekday(),
        'today': today_by_time_from_zones(today_by_zone),
        }
    return jsonify(result)

@app.route("/target_override", methods=["DELETE"])
def remove_target_override():
    """Removes the target override if in place."""
    db = get_db()
    model.TargetOverride.clear_from_db(db)
    db.commit()
    return ('', 204)

@app.route("/state", methods=["POST"])
def update_cached_state():
    """Updates the currently-cached state value.

    Expects request values 'when' (datetime) and 'state'"""
    try:
        state = request.values['state']
        when = datetime.datetime.strptime(
            request.values['when'], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ('', 400)

    db = get_db()
    model.update_last_state(db, when, state)
    db.commit()
    return ('', 200)

@app.route("/temperature", methods=["POST"])
def update_cached_temperature():
    """Updates the currently-cached temperature value.

    Expects request values 'when' (datetime) and 'temp'"""
    try:
        temp = float(request.values['temp'])
        when = datetime.datetime.strptime(
            request.values['when'], "%Y-%m-%dT%H:%M:%S")
        zone = int(request.values['zone'])
    except ValueError:
        return ('', 400)

    db = get_db()
    model.update_last_temperature(db, when, temp, zone)
    db.commit()
    return ('', 200)

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
        if not (day >= 0 and day < 7):
            raise ValueError("Day of week must be in range 0 to 7")
    except ValueError:
        return ('', 400)
    model.FullSchedule.delete_entry(db, day, time)
    db.commit()
    return ''

@app.route("/zones")
def list_zones():
    db = get_db()
    zones = model.Zone.all_from_db(db)
    return jsonify([{
                'zone_id': z.zone_id,
                'name': z.name,
                'boiler_relay': z.boiler_relay,
                'sensor': z.sensor
            } for z in zones
        ])

@app.route("/target_override", methods=["POST"])
def set_target_override():
    """Set a target override for a duration specified.

    Specify 'zone', 'temp' and at least one of 'days', 'hours', or 'mins'.
    Returns a JSON object containg 'temp' (the newly-accepted target)
    and 'until' which is a %H:%M-formatted time at which the override
    ends (so the client doesn't have to do a time calculation for this).
    """
    try:
        zone = int(request.form['zone'])

        secs = 0
        if 'days' in request.form:
            secs += int(request.form['days']) * 60 * 60 * 24
        if 'hours' in request.form:
            secs += int(request.form['hours']) * 60 * 60
        if 'mins' in request.form:
            secs += int(request.form['mins']) * 60
        if not secs:
            return 'Must specify days, hours, or mins', 400

        duration = datetime.timedelta(0, secs)
        temp = float(request.form['temp'])
    except ValueError:
        return '', 400
    now = datetime.datetime.now()
    end = now + duration

    db = get_db()
    override = model.TargetOverride(end, temp, zone)
    override.save(db)
    db.commit()

    return ('', 200)

if __name__ == "__main__":
    app.run()
