import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ConnectionState, Room, RoomEvent } from "livekit-client";

import type { DemoDefinition } from "~/lib/demo-config";

type TokenResponse = {
  server_url: string;
  participant_token: string;
  room_name: string;
  agent: string;
};

type CallPhase = "idle" | "requesting-token" | "connecting" | "connected";

type Props = {
  demo: DemoDefinition;
};

export function DemoCallPage({ demo }: Props) {
  const roomRef = useRef<Room | null>(null);
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    ConnectionState.Disconnected,
  );
  const [roomName, setRoomName] = useState<string>("");
  const [selectedAgent, setSelectedAgent] = useState<string>(demo.agent);
  const [roomMetadata, setRoomMetadata] = useState<string>("");
  const [remoteParticipantCount, setRemoteParticipantCount] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    return () => {
      void disconnectFromRoom();
    };
  }, []);

  async function startCall() {
    setErrorMessage("");
    setPhase("requesting-token");

    try {
      const response = await fetch("/api/token", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ variant: demo.slug }),
      });

      const payload = (await response.json()) as TokenResponse | { error: string };
      if (!response.ok || !("participant_token" in payload)) {
        throw new Error(
          "error" in payload ? payload.error : "Failed to create a LiveKit token.",
        );
      }

      setPhase("connecting");
      setRoomName(payload.room_name);
      setSelectedAgent(payload.agent);

      const room = new Room();
      attachRoomListeners(room);
      roomRef.current = room;

      await room.connect(payload.server_url, payload.participant_token, {
        autoSubscribe: true,
      });
      await room.localParticipant.setMicrophoneEnabled(true);

      setRoomMetadata(room.metadata ?? "");
      setRemoteParticipantCount(room.remoteParticipants.size);
      setPhase("connected");
    } catch (error) {
      setPhase("idle");
      setConnectionState(ConnectionState.Disconnected);
      setErrorMessage(
        error instanceof Error ? error.message : "Could not start the LiveKit call.",
      );
      await disconnectFromRoom();
    }
  }

  async function disconnectFromRoom() {
    const room = roomRef.current;
    roomRef.current = null;

    if (room) {
      room.removeAllListeners();
      await room.disconnect();
    }

    setPhase("idle");
    setConnectionState(ConnectionState.Disconnected);
    setRemoteParticipantCount(0);
    setRoomMetadata("");
  }

  function attachRoomListeners(room: Room) {
    room
      .on(RoomEvent.Connected, () => {
        setConnectionState(ConnectionState.Connected);
        setRoomMetadata(room.metadata ?? "");
        setRemoteParticipantCount(room.remoteParticipants.size);
      })
      .on(RoomEvent.ConnectionStateChanged, (nextState) => {
        setConnectionState(nextState);
      })
      .on(RoomEvent.Disconnected, () => {
        setConnectionState(ConnectionState.Disconnected);
        setPhase("idle");
        setRemoteParticipantCount(0);
      })
      .on(RoomEvent.ParticipantConnected, () => {
        setRemoteParticipantCount(room.remoteParticipants.size);
      })
      .on(RoomEvent.ParticipantDisconnected, () => {
        setRemoteParticipantCount(room.remoteParticipants.size);
      })
      .on(RoomEvent.RoomMetadataChanged, (nextMetadata) => {
        setRoomMetadata(nextMetadata ?? "");
      });
  }

  return (
    <main className={`demo-shell ${demo.accentClassName}`}>
      <section className="demo-panel">
        <div className="demo-topbar">
          <Link className="back-link" to="/">
            Back
          </Link>
          <span className="agent-chip">{demo.title}</span>
        </div>

        <div className="demo-hero">
          <p className="eyebrow">Single worker, targeted dispatch</p>
          <h1>{demo.title}</h1>
          <p className="hero-copy">{demo.tagline}</p>
          <p className="support-copy">{demo.description}</p>
        </div>

        <div className="status-grid">
          <StatusCard label="Frontend mode" value={demo.slug} />
          <StatusCard label="Backend agent" value={selectedAgent} />
          <StatusCard label="Room" value={roomName || "Not created yet"} />
          <StatusCard label="Connection" value={humanizeConnectionState(phase, connectionState)} />
        </div>

        <div className="call-actions">
          <button
            className="primary-button"
            disabled={phase === "requesting-token" || phase === "connecting" || phase === "connected"}
            onClick={() => {
              void startCall();
            }}
            type="button"
          >
            {phase === "requesting-token"
              ? "Creating room..."
              : phase === "connecting"
                ? "Connecting..."
                : demo.buttonLabel}
          </button>

          <button
            className="secondary-button"
            disabled={phase === "idle"}
            onClick={() => {
              void disconnectFromRoom();
            }}
            type="button"
          >
            Disconnect
          </button>
        </div>

        <div className="notes-panel">
          <h2>What this demo proves</h2>
          <ul>
            <li>This page always requests the <code>{demo.agent}</code> agent.</li>
            <li>The token route creates a room with matching room metadata.</li>
            <li>The Python worker reads that metadata and dispatches the correct agent.</li>
          </ul>
        </div>

        <div className="runtime-panel">
          <div>
            <span className="runtime-label">Remote participants</span>
            <strong>{remoteParticipantCount}</strong>
          </div>
          <div>
            <span className="runtime-label">Room metadata</span>
            <code>{roomMetadata || '{"agent": "..."}'}</code>
          </div>
        </div>

        {errorMessage ? <p className="error-banner">{errorMessage}</p> : null}
      </section>
    </main>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function humanizeConnectionState(
  phase: CallPhase,
  state: ConnectionState,
): string {
  if (phase === "requesting-token") {
    return "Requesting token";
  }
  if (phase === "connecting") {
    return "Connecting";
  }
  if (phase === "connected") {
    return "Connected";
  }
  if (state === ConnectionState.Reconnecting) {
    return "Reconnecting";
  }
  return "Idle";
}
