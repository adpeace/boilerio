import scheduler
import requests_mock
import requests.exceptions

@requests_mock.Mocker()
def test_no_exception_if_request_raises(m):
    m.get("http://scheduler/api/schedule", exc=requests.exceptions.Timeout)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None)

@requests_mock.Mocker()
def test_no_exception_if_request_fails(m):
    m.get("http://scheduler/api/schedule", status_code=401)
    scheduler.scheduler_iteration(None, None, 'http://scheduler/api', None)

