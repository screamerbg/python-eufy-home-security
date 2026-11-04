"""Counter observation from the existing P2P parameter reads, no cloud or history I/O."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from eufy_home_security.cloud.models import CloudDevice
from eufy_home_security.events import Event, MotionDetected, MotionRecorded, StationStateChanged
from eufy_home_security.models import PARAM_DETECTED_EVENTS, PARAM_RECORDED_EVENTS
from eufy_home_security.p2p.session import P2PCredentials, StationSession
from eufy_home_security.station import Station
from eufy_home_security.testing import SYNTHETIC, FakeStation

STATION = CloudDevice(
    device_sn=SYNTHETIC.station_sn,
    device_type=18,
    name="Synthetic HomeBase",
    p2p_did=SYNTHETIC.did,
    main_sw_version="3.8.7.4",
)
CAMERA = CloudDevice(
    device_sn=SYNTHETIC.camera_sn,
    device_type=19,
    name="Synthetic camera",
    station_sn=SYNTHETIC.station_sn,
    channel=0,
)


@pytest.fixture
async def station_and_fake() -> AsyncIterator[tuple[Station, FakeStation]]:
    fake = FakeStation()
    await fake.start()

    async def credentials(*, refresh: bool, cipher_id: int | None = None) -> P2PCredentials:
        return P2PCredentials(SYNTHETIC.account_id, "user", fake.ecc_private_key_hex)

    session = StationSession(
        SYNTHETIC.station_sn, credentials, host="127.0.0.1", port=fake.discovery_port
    )
    station = Station(STATION, session, sub_devices=[CAMERA])
    try:
        yield station, fake
    finally:
        await station.async_close()
        fake.stop()


async def test_counter_activity_uses_existing_parameter_read_not_cloud(
    station_and_fake: tuple[Station, FakeStation],
) -> None:
    station, fake = station_and_fake
    fake.params[0][PARAM_DETECTED_EVENTS] = "100"
    fake.params[0][PARAM_RECORDED_EVENTS] = "50"
    events: list[Event] = []
    station.subscribe(events.append)

    await station.async_update()  # first reading is a baseline
    assert not any(isinstance(e, (MotionDetected, MotionRecorded)) for e in events)

    fake.params[0][PARAM_DETECTED_EVENTS] = "103"
    await station.async_update()
    motions = [e for e in events if isinstance(e, MotionDetected)]
    assert len(motions) == 1
    assert (motions[0].source, motions[0].count) == ("counter", 3)
    assert not any(isinstance(e, MotionRecorded) for e in events)

    fake.params[0][PARAM_RECORDED_EVENTS] = "52"
    await station.async_update()
    recordings = [e for e in events if isinstance(e, MotionRecorded)]
    assert len(recordings) == 1
    assert recordings[0].count == 2
    assert any(isinstance(e, StationStateChanged) for e in events)

    await station.async_update()
    assert len([e for e in events if isinstance(e, MotionDetected)]) == 1
    assert len([e for e in events if isinstance(e, MotionRecorded)]) == 1
