import datetime
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PWM(object):
    """Performs pulse-width modulation."""
    def __init__(self, dutycycle, period, device):
        """Initialise PWM state.

        dutycycle: a timedelate representing the time duration the device
                   should be on (weird naming...).
        period: the duration of a full cycle (on + off)
        device: an object implementing on and off methods."""
        self.period = period
        self.dutycycle = None
        self.setDutyCycle(dutycycle)
        self.active = False
        self.periodBegin = None
        self.device = device

    def setDutyCycle(self, dutycycle):
        if self.dutycycle != dutycycle:
            self.dutycycle = dutycycle
            self.on_period = datetime.timedelta(0,
                self.period.total_seconds() * dutycycle)
            self.periodBegin = None

    def update(self, now):
        # Begin new cycle?
        if self.periodBegin is None or \
           self.periodBegin + self.period <= now:
            logger.debug("Beginning PWM new cycle @ %s", str(now))
            self.periodBegin = now
            self.active = self.on_period > datetime.timedelta(0, 0)
            if self.active:
                self.device.on()
            else:
                self.device.off()
            return

        # End of 'on' cycle?
        if (self.periodBegin + self.on_period) <= now:
            if self.on_period <= self.period and self.active:
                logger.debug("End of PWM duty cycle @ %s", str(now))
                self.device.off()
                self.active = False
            return

