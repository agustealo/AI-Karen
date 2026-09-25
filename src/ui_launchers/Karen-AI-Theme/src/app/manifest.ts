import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "KAREN | Local-first cognitive runtime",
    short_name: "KAREN",
    description:
      "Local-first, prompt-first AI runtime with governed memory, provider orchestration, agents, extensions, RBAC, and observability.",
    start_url: "/",
    display: "standalone",
    background_color: "#18181B",
    theme_color: "#18181B",
    categories: ["productivity", "developer", "utilities"],
    icons: [
      {
        src: "/brand/karen-mark.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
    ],
  };
}
