"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { withBuild } from "@/lib/urls";
import { BuildBar } from "./BuildBar";
import { Icon } from "./Icon";

export const NAV = [
  { href: "/", label: "Dashboard", icon: "dashboard", group: "" },
  { href: "/population", label: "Population Explorer", icon: "population", group: "Population" },
  { href: "/cohorts", label: "Cohorts", icon: "cohorts", group: "Population" },
  { href: "/personas", label: "Persona Explorer", icon: "persona", group: "Population" },
  { href: "/experiments/new", label: "New Experiment", icon: "experiment", group: "Experiments" },
  { href: "/results", label: "Results", icon: "results", group: "Experiments" },
  { href: "/validation", label: "Validation", icon: "validation", group: "Research" },
  { href: "/data-sources", label: "Data Sources", icon: "sources", group: "Research" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const build = params.get("build");
  const [open, setOpen] = useState(false);
  return (
    <div className="shell" data-page={pathname.split("/")[1] || "dashboard"}>
      <a className="skip-link" href="#main">Skip to content</a>
      <nav className="sidebar" aria-label="Workbench">
        <div className="sidebar-head">
          <div className="brand">
            <span className="brand-mark"><Icon name="network" size={22}/></span>
            <span><span className="brand-name">SocietyTwin</span><span className="brand-sub">AI-Powered Digital Society<br/>for Türkiye</span></span>
          </div>
          <button type="button" className="button small nav-toggle" aria-expanded={open} aria-controls="nav-list" onClick={() => setOpen((v) => !v)}>{open ? "Close menu" : "Menu"}</button>
        </div>
        <ul className="nav-list" id="nav-list" data-open={open ? "true" : "false"}>
          {NAV.map((item, i) => (
            <li key={item.href}>
              {item.group && (i === 0 || NAV[i - 1].group !== item.group) ? <span className="nav-group">{item.group}</span> : null}
              <Link className="nav-link" href={withBuild(item.href, build)} aria-current={(item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)) ? "page" : undefined} onClick={() => setOpen(false)}>
                <Icon name={item.icon} size={17}/><span>{item.label}</span>
              </Link>
            </li>
          ))}
        </ul>
        <div className="sidebar-foot"><span className="workspace-indicator"/><span>Local workspace<small>Changes stay on this computer</small></span></div>
      </nav>
      <div className="main">
        <BuildBar />
        <main id="main" className="content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
