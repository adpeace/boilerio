"""Deterministic worker and clock for HTTP scheduling tests."""


class InlineWorker:
    def submit(self, key, job):
        job()


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


def read_at(resource, tick):
    resource.clock.value = tick
    return resource.get()


def iterate_at(controller, *args):
    controller.clock.value = args[-1]
    controller.iteration(*args)


class HeldWorker:
    """A worker that queues jobs for explicit execution by a test."""

    def __init__(self):
        self.jobs = []

    def submit(self, key, job):
        self.jobs.append(job)

    def run_next(self):
        self.jobs.pop(0)()
