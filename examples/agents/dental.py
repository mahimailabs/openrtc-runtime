from __future__ import annotations

from livekit.agents import Agent, RunContext, function_tool


class DentalAgent(Agent):
    """Example dental reception assistant."""

    def __init__(self) -> None:
        super().__init__(
            instructions="You help patients schedule and prepare for dental visits."
        )

    @function_tool
    async def schedule_cleaning(
        self,
        context: RunContext,
        patient_name: str,
        date: str,
    ) -> str:
        """Schedule a dental cleaning.

        Args:
            context: LiveKit tool runtime context.
            patient_name: Patient's name.
            date: Preferred appointment date.

        Returns:
            A mock scheduling confirmation.
        """
        return f"Requested a cleaning appointment for {patient_name} on {date}."

    @function_tool
    async def explain_pre_visit_instructions(self, context: RunContext) -> str:
        """Explain pre-visit instructions for a patient.

        Args:
            context: LiveKit tool runtime context.

        Returns:
            A mock preparation reminder.
        """
        return "Please arrive 10 minutes early and bring your insurance information."

    @function_tool
    async def lookup_office_hours(self, context: RunContext) -> str:
        """Share office hours.

        Args:
            context: LiveKit tool runtime context.

        Returns:
            A mock office hours response.
        """
        return "The office is open Monday through Friday from 8 AM to 5 PM."
