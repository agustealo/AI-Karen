import type { Metadata } from "next";
import { Inter } from "next/font/google";

import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "KAREN | Local-first cognitive runtime",
    template: "%s | KAREN",
  },
  description:
    "KAREN is a local-first, prompt-first AI runtime for governed chat execution, durable memory, provider orchestration, agents, extensions, and observable automation.",
  applicationName: "KAREN",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/brand/karen-mark.svg",
    shortcut: "/brand/karen-mark.svg",
  },
  openGraph: {
    type: "website",
    title: "KAREN | Local-first cognitive runtime",
    description: "Local by default. Governed by design.",
    images: [
      {
        url: "/brand/karen-banner.svg",
        width: 1600,
        height: 500,
        alt: "KAREN, local by default and governed by design",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "KAREN | Local-first cognitive runtime",
    description: "Local by default. Governed by design.",
    images: ["/brand/karen-banner.svg"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css"
        />
      </head>
      <body className={`${inter.className} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
