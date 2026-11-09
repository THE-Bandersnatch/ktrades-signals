import type { MetadataRoute } from "next";

// Web app manifest. The Android (Trusted Web Activity) build reads its name,
// colours and icons from here, so keep it in step with the Play listing.
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "KTRADES Signals",
    short_name: "KTRADES",
    description:
      "Live Binance futures funding-rate signals with chart-confirmed entries and a public track record.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#06090a",
    theme_color: "#06090a",
    categories: ["finance"],
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
