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

def get_tgt_override_json(db):
    target_override_obj = model.TargetOverride.from_db(db)
    if target_override_obj:
        return {
            'until': target_override_obj.end.strftime("%Y-%m-%dT%H:%M"),
            'temp': target_override_obj.temp
            }
    else:
        return {}

@app.route("/summary")
def get_summary():
    now = datetime.datetime.now()
    db = get_db()

    schedule = model.FullSchedule.from_db(db)
    tgt_override = get_tgt_override_json(db)
    tgt_override_obj = model.TargetOverride.from_db(db)
    scheduler = SchedulerTemperaturePolicy(
        schedule, tgt_override_obj)
    target = scheduler.target(now)

    today = scheduler.get_day(now.weekday())
    today = [{'time': starttime.strftime("%H:%M"), 'temp': temp}
             for (starttime, temp) in today]
    temp = model.get_last_temperature(db)
    cached_temp = temp.temp if temp else None

    db.commit()
    result = {
        'target': target[0],
        'target_entry': target[1],
        'target_overridden': target[1] == -2,
        'current': cached_temp,
        'server_day_of_week': now.weekday(),
        'today': today,
        'target_override': tgt_override,
        }
    return jsonify(result)

@app.route("/target_override", methods=["DELETE"])
def remove_target_override():
    """Removes the target override if in place."""
    db = get_db()
    model.TargetOverride.clear_from_db(db)
    db.commit()
    return ('', 204)

@app.route("/temperature", methods=["POST"])
def update_cached_temperature():
    """Updates the currently-cached temperature value.

    Expects request values 'when' (datetime) and 'temp'"""
    try:
        temp = float(request.values['temp'])
        when = datetime.datetime.strptime(
            request.values['when'], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ('', 400)

    db = get_db()
    model.update_last_temperature(db, when, temp)
    db.commit()
    return ('', 200)

@app.route("/schedule")
def get_schedule():
    db = get_db()
    full_schedule = model.FullSchedule.from_db(db)
    json_schedule = {}
    for dow in range(7):
        json_schedule[dow] = []
    for entry in full_schedule:
        entry_dow, entry_start, entry_temp = entry
        dow = json_schedule[entry_dow]
        dow.append({
            'time': entry_start.strftime('%H:%M'),
            'temp': entry_temp
            })
    tgt_override = get_tgt_override_json(db)
    db.commit()
    return jsonify({
        'schedule': json_schedule,
        'target_override': tgt_override
        })

@app.route("/schedule/new_entry", methods=["POST"])
def add_schedule_entry():
    db = get_db()
    try:
        print request.values
        time = datetime.datetime.strptime(request.values['time'], "%H:%M")
        time = time.time()
        day = int(request.values['day'])
        if not (day >= 0 and day < 7):
            raise ValueError("Day of week must be in range 0 to 7")
        temp = float(request.values['temp'])
        if not (temp >= 0 and temp < 35):
            raise ValueError("Target tempt must be in range 0 to 35")
    except ValueError:
        return ('', 400)
    model.FullSchedule.create_entry(db, day, time, temp)
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

@app.route("/target_override", methods=["POST"])
def set_target_override():
    """Set a target override for a duration specified.

    Specify 'temp' and at least one of 'days', 'hours', or 'mins'.
    Returns a JSON object containg 'temp' (the newly-accepted target)
    and 'until' which is a %H:%M-formatted time at which the override
    ends (so the client doesn't have to do a time calculation for this).
    """
    try:
        secs = 0
        if 'days' in request.form:
            secs += int(request.form['days']) * 60 * 60 * 24
        if 'hours' in request.form:
            secs += int(request.form['hours']) * 60 * 60
        if 'mins' in request.form:
            secs += int(request.form['mins']) * 60
        if not secs:
            return # XXX exception

        duration = datetime.timedelta(0, secs)
        temp = float(request.form['temp'])
    except ValueError:
        return '', 400
    now = datetime.datetime.now()
    end = now + duration

    db = get_db()
    override = model.TargetOverride(end, temp)
    override.save(db)
    db.commit()

    return ('', 200)

if __name__ == "__main__":
    app.run()
