import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { BuildProvider } from "@/lib/build";
import { PopulationProvider } from "@/lib/population";
import "./globals.css";

export const metadata: Metadata = {
  title: "SocietyTwin",
  description: "Türkiye synthetic population calibrated to official aggregate statistics, cohorts, personas and controlled AI experiments.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <Suspense fallback={<p className="muted" style={{ padding: 24 }}>Loading workbench…</p>}>
          <PopulationProvider>
            <BuildProvider>
              <AppShell>{children}</AppShell>
            </BuildProvider>
          </PopulationProvider>
        </Suspense>
      </body>
    </html>
  );
}
