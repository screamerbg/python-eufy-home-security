"""Counter-based motion activity: no history queries, tasks, or extra I/O."""

from __future__ import annotations

from datetime import UTC

from eufy_home_security.events import (
    DetectionType,
    EventSource,
    MotionDetected,
    MotionRecorded,
    SecurityEvent,
)
from eufy_home_security.station import StationState, SubDeviceState
from eufy_home_security.station.activity import StationActivity

CAMERA = "T8113P0000000001"
STATION = "T8010P0000000001"


class FakeActivityStation:
    serial = STATION


def state(
    detected: int | None,
    recorded: int | None,
    *,
    online: bool | None = True,
    serial: str | None = CAMERA,
) -> StationState:
    return StationState(
        serial=STATION,
        guard_mode=None,
        firmware=None,
        params={},
        devices={
            0: SubDeviceState(
                channel=0,
                serial=serial,
                name=None,
                battery=None,
                firmware=None,
                params={},
                online=online,
                detected_events=detected,
                recorded_events=recorded,
            )
        },
    )


def test_both_counters_emit_one_aggregate_event_each() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(100, 50))
    activity.observe(state(103, 52))
    activity.observe(state(103, 52))
    assert [type(event) for event in emitted] == [MotionDetected, MotionRecorded]
    assert [event.count for event in emitted] == [3, 2]
    assert [event.device_sn for event in emitted] == [CAMERA, CAMERA]
    assert all(event.observed_at.tzinfo is UTC for event in emitted)


def test_single_counter_change_does_not_trigger_other_event() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(1, 1))
    activity.observe(state(2, 1))
    assert [type(event) for event in emitted] == [MotionDetected]
    activity.observe(state(2, 2))
    assert [type(event) for event in emitted] == [MotionDetected, MotionRecorded]


def test_resets_offline_missing_and_startup_do_not_fire() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(10, 10))
    activity.observe(state(1, 1))  # counter reset; rebaseline
    activity.observe(state(None, None))
    activity.observe(state(2, 2))  # first numeric after missing; rebaseline
    activity.observe(state(99, 99, online=False))
    activity.observe(state(3, 3))  # first good value after offline; rebaseline
    activity.observe(state(3, 3))
    assert emitted == []
    activity.observe(state(4, 3))
    assert len(emitted) == 1


def test_disappearing_and_unidentified_devices_do_not_create_events() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(10, 10))
    activity.observe(state(11, 11, serial=None))
    activity.observe(state(20, 20))  # missing device first reappears; baseline
    assert emitted == []


def test_push_is_fallback_only_when_counter_missing() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(None, 3))
    event = SecurityEvent(
        source=EventSource.P2P,
        station_sn=STATION,
        device_sn=CAMERA,
        event_type=int(DetectionType.PERSON),
    )
    activity.on_security_event(event)
    assert len(emitted) == 1
    assert isinstance(emitted[0], MotionDetected)
    assert (emitted[0].source, emitted[0].count) == ("push", 1)
    activity.observe(state(10, 3))  # new counter appears: baseline only
    activity.on_security_event(event)
    assert len(emitted) == 1
    activity.observe(state(11, 3))
    assert len(emitted) == 2
    assert isinstance(emitted[-1], MotionDetected)
    assert emitted[-1].source == "counter"


def test_push_ignores_enrichments_unpaired_and_offline() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    event = SecurityEvent(
        source=EventSource.P2P,
        station_sn=STATION,
        device_sn=CAMERA,
        event_type=int(DetectionType.MOTION),
    )
    activity.on_security_event(event)  # no state yet
    activity.observe(state(None, None, online=False))
    activity.on_security_event(event)  # offline
    activity.observe(state(None, None))
    activity.on_security_event(
        SecurityEvent(
            source=EventSource.P2P,
            station_sn=STATION,
            device_sn="not-paired",
            event_type=int(DetectionType.MOTION),
        )
    )
    activity.on_security_event(
        SecurityEvent(
            source=EventSource.P2P,
            station_sn=STATION,
            device_sn=CAMERA,
            event_type=int(DetectionType.MOTION),
            enriches=True,
        )
    )
    assert emitted == []
    activity.on_security_event(event)
    assert len(emitted) == 1


def test_synchronous_observation_and_restart() -> None:
    emitted: list[MotionDetected | MotionRecorded] = []
    activity = StationActivity(FakeActivityStation(), emitted.append)
    activity.observe(state(5, 5))  # synchronous: no running event loop needed
    activity.observe(state(6, 6))
    assert len(emitted) == 2
    activity.reopen()
    activity.observe(state(100, 100))  # baseline again after restart
    assert len(emitted) == 2
