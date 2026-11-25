from datetime import time

from .. import model
from .. import app

def test_today_pivot_merge_entries():
    # zoneid -> [ (start, zoneid, temp) ]:
    data = {1: [
                (time(0, 0), 1, 10),
                (time(10, 45), 1, 15),
               ],
            2: [
                (time(0, 0), 2, 12),
                (time(10, 50), 2, 17),
               ],
           }
    expected_result = [
                        {'when': '00:00', 'zones': [
                            {'zone': 1, 'temp': 10},
                            {'zone': 2, 'temp': 12},
                            ]},
                        {'when': '10:45', 'zones': [
                            {'zone': 1, 'temp': 15}
                            ]},
                        {'when': '10:50', 'zones': [
                            {'zone': 2, 'temp': 17}
                            ]},
                      ]
    assert app.today_by_time_from_zones(data) == expected_result

def test_get_schedule_simple():
    entries = [
        (0, time(10,0), 1, 10),
        ]
    expected_result = {
        0: [{'when': "10:00", 'zones': [{'zone': 1, 'temp': 10}]}],
        1: [], 2: [], 3: [], 4: [], 5: [], 6: [],
        }
    fullsched = model.FullSchedule(entries)
    assert app.full_schedule_to_dict(fullsched) == expected_result

def test_get_schedule_simultaneous_change():
    entries = [
        (0, time(10,0), 1, 10),
        (0, time(10,0), 2, 10),
        ]
    expected_result = {
        0: [{'when': "10:00", 'zones': [{'zone': 1, 'temp': 10}, {'zone': 2, 'temp': 10}]}],
        1: [], 2: [], 3: [], 4: [], 5: [], 6: [],
        }
    fullsched = model.FullSchedule(entries)
    assert app.full_schedule_to_dict(fullsched) == expected_result
