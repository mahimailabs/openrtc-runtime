"""Print how many of a run's rooms still have participants, then delete all rooms."""

import asyncio
import sys

from livekit import api


async def main(label: str) -> None:
    lk = api.LiveKitAPI()
    rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
    print(
        sum(
            1
            for r in rooms
            if r.name.startswith(f"{label}-") and r.num_participants > 0
        )
    )
    for r in rooms:
        await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
    await lk.aclose()


asyncio.run(main(sys.argv[1]))
