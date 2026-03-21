import { AccessToken, RoomServiceClient } from "livekit-server-sdk";

import type { Route } from "./+types/api.token";
import {
  DEMO_DEFINITIONS,
  isDemoVariant,
  type BackendAgent,
  type DemoVariant,
} from "~/lib/demo-config";

type TokenErrorBody = {
  error: string;
};

type TokenSuccessBody = {
  server_url: string;
  participant_token: string;
  room_name: string;
  agent: BackendAgent;
};

export async function action({ request }: Route.ActionArgs) {
  const body = (await request.json()) as { variant?: string };
  if (!body.variant || !isDemoVariant(body.variant)) {
    return Response.json(
      { error: "Choose either dentist or restaurant." },
      { status: 400 },
    );
  }

  const livekitUrl = process.env.LIVEKIT_URL;
  const livekitApiKey = process.env.LIVEKIT_API_KEY;
  const livekitApiSecret = process.env.LIVEKIT_API_SECRET;

  if (!livekitUrl || !livekitApiKey || !livekitApiSecret) {
    return Response.json(
      {
        error:
          "Missing LIVEKIT_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET in the frontend server environment.",
      },
      { status: 500 },
    );
  }

  const selectedDemo = DEMO_DEFINITIONS[body.variant];
  const roomName = buildRoomName(selectedDemo.agent);
  const participantIdentity = buildParticipantIdentity(body.variant);
  const roomMetadata = JSON.stringify({ agent: selectedDemo.agent });

  const roomService = new RoomServiceClient(
    toRoomServiceUrl(livekitUrl),
    livekitApiKey,
    livekitApiSecret,
  );

  try {
    await roomService.createRoom({
      name: roomName,
      metadata: roomMetadata,
    });

    const token = new AccessToken(livekitApiKey, livekitApiSecret, {
      identity: participantIdentity,
      name: `${selectedDemo.title} Caller`,
      ttl: "10m",
    });

    token.addGrant({
      roomJoin: true,
      room: roomName,
      canPublish: true,
      canSubscribe: true,
    });

    return Response.json(
      {
        server_url: livekitUrl,
        participant_token: await token.toJwt(),
        room_name: roomName,
        agent: selectedDemo.agent,
      },
      { status: 201 },
    );
  } catch (error) {
    console.error("Could not create LiveKit demo token", error);
    return Response.json(
      { error: "Could not create a LiveKit room or access token." },
      { status: 500 },
    );
  }
}

function buildRoomName(agent: BackendAgent): string {
  return `${agent}-${crypto.randomUUID().slice(0, 8)}`;
}

function buildParticipantIdentity(variant: DemoVariant): string {
  return `${variant}-viewer-${crypto.randomUUID().slice(0, 8)}`;
}

function toRoomServiceUrl(livekitUrl: string): string {
  if (livekitUrl.startsWith("ws://")) {
    return `http://${livekitUrl.slice("ws://".length)}`;
  }
  if (livekitUrl.startsWith("wss://")) {
    return `https://${livekitUrl.slice("wss://".length)}`;
  }
  return livekitUrl;
}
