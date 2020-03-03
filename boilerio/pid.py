import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PID(object):
    """PID controller.

    Designed for single-direction applications, i.e. a motor that spins in one
    direction with varying power.
    """

    def __init__(self, setpoint, Kp, Ki, Kd, min_output=0.15):
        """Initialize PID controller.

        min_output defines the lowest value the output can take, beyond which
        it will get dropped to 0.  The controller is output is constrained at a
        maximum of 1."""
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.last_prop = 0.0
        self.last_pv = None
        self.min_output = min_output
        self.reset(setpoint)

    def reset(self, setpoint):
        """Change setpoint.

        This also resets internal tracking of error and differentials.
        """
        self.setpoint = setpoint
        self.last_diff = 0
        self.error_integral = 0

    def update(self, pv):
        """Update with a new present value.  Returns PID output."""
        if self.last_pv is None:
            self.last_pv = pv

        error = self.setpoint - pv

        # Constrain total error to avoid windup problems
        self.error_integral += self.Ki * error
        self.error_integral = max(min(self.error_integral, 1), -1)
        diff = pv - self.last_pv

        self.last_diff = self.Kd * diff
        self.last_prop = self.Kp * error
        self.last_pv = pv

        out = self.Kp * error + self.error_integral - self.Kd * diff
        if out < self.min_output:
            rv = 0
        else:
            rv = min(out, 1)
        logger.debug("Unconstrained pid return value %f -> %f", out, rv)

        return rv
