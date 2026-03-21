import type { Route } from "./+types/dentist";
import { DemoCallPage } from "~/components/demo-call-page";
import { DEMO_DEFINITIONS } from "~/lib/demo-config";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Dentist Demo" },
    {
      name: "description",
      content: "Starts the dental OpenRTC agent from the frontend example.",
    },
  ];
}

export default function DentistRoute() {
  return <DemoCallPage demo={DEMO_DEFINITIONS.dentist} />;
}
