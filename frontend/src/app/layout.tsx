import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { BuildProvider } from "@/lib/build";
import "./globals.css";

export const metadata: Metadata = {
  title: "SocietyTwin Workbench",
  description: "Research workbench for the SocietyTwin synthetic Ankara population, cohorts, personas and recorded MatrAIx results.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<p className="muted" style={{ padding: 24 }}>Loading workbench…</p>}>
          <BuildProvider>
            <AppShell>{children}</AppShell>
          </BuildProvider>
        </Suspense>
      </body>
    </html>
  );
}
