from __future__ import annotations

from livekit.agents import Agent, RunContext, function_tool


class RestaurantAgent(Agent):
    """Example restaurant reservation assistant."""

    def __init__(self) -> None:
        super().__init__(instructions="You help callers book and manage restaurant reservations.")

    @function_tool
    async def check_availability(self, context: RunContext, party_size: int, time: str) -> str:
        """Check whether a reservation slot is available.

        Args:
            context: LiveKit tool runtime context.
            party_size: Number of diners.
            time: Requested reservation time.

        Returns:
            A mock reservation availability response.
        """
        return f"We can usually accommodate {party_size} guests around {time}."

    @function_tool
    async def create_reservation(self, context: RunContext, name: str, time: str) -> str:
        """Create a reservation request.

        Args:
            context: LiveKit tool runtime context.
            name: Reservation name.
            time: Requested reservation time.

        Returns:
            A mock booking confirmation.
        """
        return f"Tentatively booked a table for {name} at {time}."

    @function_tool
    async def get_menu_highlights(self, context: RunContext) -> str:
        """Provide a short overview of menu highlights.

        Args:
            context: LiveKit tool runtime context.

        Returns:
            A mock menu summary.
        """
        return "Tonight's highlights include handmade pasta, salmon, and tiramisu."
