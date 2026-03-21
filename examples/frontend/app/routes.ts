import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("dentist", "routes/dentist.tsx"),
  route("restaurant", "routes/restaurant.tsx"),
  route("api/token", "routes/api.token.ts"),
] satisfies RouteConfig;
