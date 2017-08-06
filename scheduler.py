#!/usr/bin/env python

"""Operate heating schedule."""

import sys
import json
import datetime
import threading
import paho.mqtt.client as mqtt
import logging
import requests

import model
import config

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

strptime = datetime.datetime.strptime

def get_db(conf):
    db = model.db_connect(
        conf.get('heating', 'scheduler_db_host'),
        conf.get('heating', 'scheduler_db_name'),
        conf.get('heating', 'scheduler_db_user'),
        conf.get('heating', 'scheduler_db_password'))
    return db

class SchedulerTemperaturePolicy(object):
    ENTRY_TARGET_OVERRIDE = -2

    def __init__(self, schedule, tgt_override):
        self.schedule = schedule
        self.target_override = tgt_override

    @classmethod
    def from_json(cls, j):
        data = json.loads(j)

        entries = []
        for day in sorted(data['schedule']):
            for item in data['schedule'][day]:
                entries.append((
                    int(day),
                    strptime(item['time'], "%H:%M").time(),
                    item['temp']
                    ))
        schedule = model.FullSchedule(entries)
        tgt_override = data['target_override']
        if all(x in tgt_override for x in ['temp', 'until']):
            tgt_override_obj = model.TargetOverride(
                strptime(tgt_override['until'], '%Y-%m-%dT%H:%M'),
                tgt_override['temp'])
        else:
            tgt_override = None
        return cls(schedule, tgt_override_obj)

    def get_day(self, day):
        """Determine the schedule for today covering the full 24h.

        Uses the overall schedule and any schedule overrides (but not
        target tmperature overrides) in place.
        """
        if len(self.schedule.entries) == 0:
            return []
        entries = []

        # Populate with the day's entries.  Add an entry from the start
        # of the day based on entry prior to that day:
        candidate_beginning = None
        for sday, starttime, temp in self.schedule.entries:
            if sday == day:
                entries.append((starttime, temp))
            elif sday < day:
                candidate_beginning = temp
        if candidate_beginning is None:
            # Wasn't an earlier entry, use the last one in the schedule:
            _, _, temp = self.schedule.entries[-1]
            candidate_beginning = temp
        # Check whether we need to fill in the start:
        if entries[0][0] != datetime.time(0,0):
            entries.insert(0, (datetime.time(0,0), candidate_beginning))

        return entries

    def target(self, now):
        """Determine temperature target at datetime now.

        Returns a pair of (target, index) where index is the number of the
        entry in the day's schedule returned by get_day. Index is -1 if from a
        target override.
        """
        # First check if we are still within an override:
        if self.target_override is not None:
            if self.target_override.end > now:
                return (self.target_override.temp,
                        self.ENTRY_TARGET_OVERRIDE)

        day_schedule = self.get_day(now.weekday())
        now_time = now.time()

        # Iterate over the schedule finding the last entry with a lower time
        # than the requested time.  If we don't find one, we need the last
        # entry from the day before.
        entry = -1
        for sched_time, sched_target in day_schedule:
            if sched_time <= now_time:
                target = sched_target
                entry += 1
            else:
                break

        return target, entry

def mqtt_on_connect(client, userdata, flags, rc):
    if rc:
        logger.error("Error connecting, rc %d", rc)
        return
    client.subscribe(userdata['thermostat_schedule_change_topic'])
    client.subscribe(userdata['thermostat_status_topic'])
    client.subscribe(userdata['temperature_sensor_topic'])

def mqtt_on_message(client, userdata, msg):
    if msg.topic == userdata['thermostat_schedule_change_topic']:
        userdata['timer_event'].set()
    elif msg.topic == userdata['thermostat_status_topic']:
        if json.loads(msg.payload)['status'] == 'online':
            userdata['timer_event'].set()
    elif msg.topic == userdata['temperature_sensor_topic']:
        data = json.loads(msg.payload)
        if 'temperature' in data:
            try:
                db = get_db(userdata['conf'])
                temp = float(data['temperature'])
                model.update_last_temperature(
                    db, datetime.datetime.now(), temp)
                db.commit()
                logger.info("Cached temperature update %.2f", temp)
            except ValueError:
                pass

def on_timer(mqttc, conf, sched):
    now = datetime.datetime.now()

    scheduler = SchedulerTemperaturePolicy.from_json(sched)
    target = scheduler.target(now)
    logger.info("Publishing temperature update: %d", target[0])
    mqttc.publish(conf.get('heating', 'target_temp_topic'),
                  json.dumps({'target': target[0]}))

def main():
    conf = config.load_config()
    period_event = threading.Event()
    mqttc = mqtt.Client(userdata={
        'conf': conf,
        'thermostat_status_topic':
            conf.get('heating', 'thermostat_status_topic'),
        'thermostat_schedule_change_topic':
            conf.get('heating', 'thermostat_schedule_change_topic'),
        'temperature_sensor_topic':
            conf.get('heating', 'temperature_sensor_topic'),
        'timer_event': period_event,
        })
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    mqttc.on_message = mqtt_on_message
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    if len(sys.argv) == 2:
        scheduler_url = sys.argv[1]
    else:
        scheduler_url = conf.get('heating', 'scheduler_url')

    mqttc.loop_start()
    while True:
        try:
            r = requests.get(scheduler_url + "/schedule").text
            on_timer(mqttc, conf, r)
        except psycopg2.OperationalError:
            logger.error("Failed interval due to database error")

        period_event.wait(timeout=60)
        period_event.clear()

    mqttc.loop_stop()

if __name__ == "__main__":
    main()
