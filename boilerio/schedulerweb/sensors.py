import datetime
from flask_restx import Namespace, Resource, fields

from . import model
from .util import get_db, csrf_protection

api = Namespace('Sensors', title="Sensor readings and management")


a_sensor = api.model("Sensor", {
    'sensor_id': fields.Integer(description="Sensor ID"),
    'name': fields.String(description="Friendly name of sensor"),
    'locator': fields.String(
        description="How to find readings for the sensor locally.  This will "
        "be an MQTT topic to subscribe to.")
})


@api.route('/')
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


@api.route('/<int:sensor_id>/readings')
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
    @csrf_protection
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