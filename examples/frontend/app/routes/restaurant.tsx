import type { Route } from "./+types/restaurant";
import { DemoCallPage } from "~/components/demo-call-page";
import { DEMO_DEFINITIONS } from "~/lib/demo-config";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Restaurant Demo" },
    {
      name: "description",
      content: "Starts the restaurant OpenRTC agent from the frontend example.",
    },
  ];
}

export default function RestaurantRoute() {
  return <DemoCallPage demo={DEMO_DEFINITIONS.restaurant} />;
}
