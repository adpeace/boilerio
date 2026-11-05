import logging
from datetime import timedelta
from typing import Protocol

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class OnOffDevice(Protocol):
    """Device whose output can be switched on and off."""

    def on(self) -> None: ...

    def off(self) -> None: ...


class PWM(object):
    """Performs pulse-width modulation."""
    def __init__(self, dutycycle: float, period: timedelta, device: OnOffDevice) -> None:
        """Initialise PWM state.

        dutycycle: fraction of the period the device should be on.
        period: a timedelta for a full cycle (on + off)
        device: an object implementing on and off methods."""
        self.period: float = period.total_seconds()
        self.dutycycle: float | None = None
        self.on_period: float
        self.setDutyCycle(dutycycle)
        self.active: bool = False
        self.periodBegin: float | None = None
        self.device: OnOffDevice = device

    def setDutyCycle(self, dutycycle: float) -> None:
        if self.dutycycle != dutycycle:
            self.dutycycle = dutycycle
            self.on_period = self.period * dutycycle
            self.periodBegin = None

    def update(self, now: float) -> None:
        """Advance the output using monotonic elapsed seconds.

        :param float now: A reading from time.monotonic(), with an arbitrary
            origin. Use the same nondecreasing clock for every call on this
            instance. Tests and simulations may supply simulated elapsed seconds.
        """
        # Begin new cycle?
        if self.periodBegin is None or \
           self.periodBegin + self.period <= now:
            logger.debug("Beginning PWM new cycle @ %s", str(now))
            self.periodBegin = now
            self.active = self.on_period > 0
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

