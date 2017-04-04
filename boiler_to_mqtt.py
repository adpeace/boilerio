#!/usr/bin/python

import argparse
import serial
import sys
import ConfigParser
import paho.mqtt.client as mqtt
import json

CONFIG_PATH = '/etc/sensors/config'

def load_config(path):
    cfg = ConfigParser.RawConfigParser()
    with open(path, 'r') as f:
        cfg.readfp(f)

    return {
        'mqtt_host': cfg.get('mqtt', 'host'),
        'mqtt_user': cfg.get('mqtt', 'user'),
        'mqtt_password': cfg.get('mqtt', 'password'),
        'heating_zone_basetopic': cfg.get('heating', 'info_basetopic'),
        'heating_demand_topic': cfg.get('heating', 'demand_request_topic'),
        }

def on_connect(client, userdata, flags, rc):
    if rc:
        print "Error connecting, rc %d" % rc
        return
    print "Subscribing to %s" % userdata['demand_topic']
    client.subscribe(userdata['demand_topic'])

# I'm not sure this is a good idea...
def on_message(client, userdata, msg):
    if msg.topic != userdata['demand_topic']:
        return

    if 'sensor_file' not in userdata:
        raise RuntimeError, "Not initialised"

    try:
        request = json.loads(msg.payload)
    except:
        print "Error parsing request"
        return

    if 'command' not in request or \
       request['command'] not in ['O', 'X', 'L']:
        print "Invalid or no command specified"
    if 'thermostat' not in request:
        print "Invalid or no thermostat ID specified"
    userdata['sensor_file'].write("{}{}\n".format(
        request['command'], hex(request['thermostat'])))

def main(mqtt_host, mqtt_user, mqtt_password, zone_basetopic, demand_topic):
    userdata = {'demand_topic': demand_topic}

    client = mqtt.Client(userdata=userdata)
    client.username_pw_set(mqtt_user, mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(mqtt_host, 1883, 60)

    client.loop_start()
    try:
        sensor_filename = sys.argv[1]
        with serial.Serial(sensor_filename, 57600, timeout=None) as \
             sensor_file:
            userdata['sensor_file'] = sensor_file

            while True:
                data = sensor_file.readline().strip()
                try:
                    direction, tid, cmd = data.split()
                except:
                    continue
                print "Publishing to {}/{} : {}".format(
                    zone_basetopic, tid, json.dumps({'direction': direction,
                                                     'cmd': cmd}))
                client.publish("{}/{}".format(zone_basetopic, tid),
                               json.dumps({'thermostat': tid,
                                           'direction': direction,
                                           'cmd': cmd}))
    finally:
        client.loop_stop()

if __name__ == "__main__":
    conf = load_config(CONFIG_PATH)
    main(conf['mqtt_host'], conf['mqtt_user'], conf['mqtt_password'],
         conf['heating_zone_basetopic'], conf['heating_demand_topic'])
