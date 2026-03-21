from pathlib import Path

from dotenv import load_dotenv
from livekit.plugins import openai

from openrtc import AgentPool

load_dotenv()


def main() -> None:
    pool = AgentPool(
        default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
        default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
        default_tts=openai.TTS(model="gpt-4o-mini-tts"),
    )
    pool.discover(Path(__file__).with_name("agents"))
    pool.run()


if __name__ == "__main__":
    main()
