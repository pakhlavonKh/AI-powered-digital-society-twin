"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { withBuild } from "@/lib/urls";
import { BuildBar } from "./BuildBar";

export const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/population", label: "Population Explorer" },
  { href: "/cohorts", label: "Cohorts" },
  { href: "/personas", label: "Persona Explorer" },
  { href: "/experiments/new", label: "New Experiment" },
  { href: "/results", label: "Results" },
  { href: "/validation", label: "Validation / Data Sources", also: ["/data-sources"] },
] as const;

function isActive(pathname: string, item: (typeof NAV)[number]): boolean {
  if (item.href === "/") return pathname === "/";
  const prefixes = [item.href, ...("also" in item ? item.also : [])];
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const build = params.get("build");
  const [open, setOpen] = useState(false);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <nav className="sidebar" aria-label="Workbench">
        <div className="sidebar-head">
          <div className="brand">
            <span className="brand-name">SocietyTwin</span>
            <span className="brand-sub">Research workbench</span>
          </div>
          <button type="button" className="button small nav-toggle" aria-expanded={open} aria-controls="nav-list" onClick={() => setOpen((v) => !v)}>
            {open ? "Close menu" : "Menu"}
          </button>
        </div>
        <ol className="nav-list" id="nav-list" data-open={open ? "true" : "false"}>
          {NAV.map((item, i) => (
            <li key={item.href}>
              <Link className="nav-link" href={withBuild(item.href, build)} aria-current={isActive(pathname, item) ? "page" : undefined}
                onClick={() => setOpen(false)}>
                <span className="nav-step" aria-hidden="true">{i + 1}</span>
                <span>{item.label}</span>
              </Link>
            </li>
          ))}
        </ol>
        <p className="sidebar-foot">Local development service. Not an authenticated deployment.</p>
      </nav>
      <div className="main">
        <BuildBar />
        <main id="main" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
