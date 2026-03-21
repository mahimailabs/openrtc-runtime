from pathlib import Path

from dotenv import load_dotenv

from openrtc import AgentPool

load_dotenv()


def main() -> None:
    pool = AgentPool(
        default_stt="deepgram/nova-3:multi",
        default_llm="openai/gpt-4.1-mini",
        default_tts="cartesia/sonic-3",
    )
    pool.discover(Path(__file__).with_name("agents"))
    pool.run()


if __name__ == "__main__":
    main()
