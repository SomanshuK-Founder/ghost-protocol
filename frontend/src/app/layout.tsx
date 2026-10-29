import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "./globals.css";
import { SessionBoundary } from "@/components/session";
import { Shell } from "@/components/shell";

export const metadata: Metadata = {
  title: "Ghost Protocol — Control room",
  description: "Personal AI. Human authority. Local offline control room.",
  robots: { index: false, follow: false },
};
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionBoundary>
          <Shell>{children}</Shell>
        </SessionBoundary>
      </body>
    </html>
  );
}
