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


a_latest_reading = api.model("Latest sensor reading", {
    'when': fields.DateTime(description="When the reading occurred"),
    'value': fields.Float(description="The reading"),
})

a_latest_readings = api.model("Latest sensor readings", {
    metric_type: fields.Nested(a_latest_reading, allow_null=True)
    for metric_type in model.SENSOR_METRIC_TYPES
})

a_sensor_summary = api.model("Sensor summary", {
    'sensor_id': fields.Integer(description="Sensor ID"),
    'name': fields.String(description="Friendly name of sensor"),
    'readings': fields.Nested(a_latest_readings, skip_none=True),
})


@api.route('/summary')
class SensorSummary(Resource):
    """All configured sensors with their latest readings, keyed by metric type."""
    @api.marshal_list_with(a_sensor_summary)
    def get(self):
        summaries = {}
        for sensor_id, name, reading in model.Sensor.latest_readings_from_db(get_db()):
            summary = summaries.setdefault(sensor_id, {
                'sensor_id': sensor_id, 'name': name, 'readings': {},
            })
            if reading is not None:
                summary['readings'][reading.metric_type] = reading
        return list(summaries.values())


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
        try:
            when = datetime.datetime.fromisoformat(api.payload['when'])
            reading = model.SensorReading(
                int(sensor_id),
                when,
                api.payload['metric_type'],
                float(api.payload['value'])
                )
        except (ValueError, KeyError, TypeError):
            return 'when must be an ISO timestamp with a UTC offset', 400
        db = get_db()
        reading.save(db)
        db.commit()
