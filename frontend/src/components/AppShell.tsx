"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { withBuild } from "@/lib/urls";
import { withPop } from "@/lib/population";
import { BuildBar } from "./BuildBar";
import { Icon } from "./Icon";
import { PopulationBar } from "./PopulationBar";

// Historical Run3 sits with the experiments it belongs to; its "Recorded" tag marks it as preserved output, not a live run.
export const NAV: { href: string; label: string; icon: string; group: string; tag?: string; title?: string }[] = [
  { href: "/", label: "Dashboard", icon: "dashboard", group: "" },
  { href: "/population", label: "Population", icon: "population", group: "Population" },
  { href: "/cohorts", label: "Cohorts", icon: "cohorts", group: "Population" },
  { href: "/personas", label: "Personas", icon: "persona", group: "Population" },
  { href: "/experiments/new", label: "New Experiment", icon: "experiment", group: "Experiments" },
  { href: "/experiments", label: "Experiments", icon: "layers", group: "Experiments" },
  { href: "/results", label: "Results", icon: "results", group: "Experiments" },
  { href: "/historical", label: "Historical Run3", icon: "archive", group: "Experiments", tag: "Recorded proof of concept",
    title: "Historical Ankara proof of concept (recorded MatrAIx run3)" },
  { href: "/validation", label: "Validation", icon: "validation", group: "Research" },
  { href: "/data-sources", label: "Data Sources", icon: "sources", group: "Research" },
  { href: "/settings", label: "Settings", icon: "network", group: "" },
];

function isCurrent(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/experiments") return pathname === "/experiments";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const historical = pathname.startsWith("/historical");
  const pop = params.get("pop");
  const build = params.get("build");
  const [open, setOpen] = useState(false);
  return (
    <div className="shell" data-page={pathname.split("/")[1] || "dashboard"}>
      <a className="skip-link" href="#main">Skip to content</a>
      <nav className="sidebar" aria-label="Workbench">
        <div className="sidebar-head">
          <div className="brand">
            <span className="brand-mark"><Icon name="network" size={22}/></span>
            <span><span className="brand-name">SocietyTwin</span><span className="brand-sub">Synthetic society experiments<br/>for Türkiye</span></span>
          </div>
          <button type="button" className="button small nav-toggle" aria-expanded={open} aria-controls="nav-list" onClick={() => setOpen((v) => !v)}>{open ? "Close menu" : "Menu"}</button>
        </div>
        <ul className="nav-list" id="nav-list" data-open={open ? "true" : "false"}>
          {NAV.map((item, i) => (
            <li key={item.href}>
              {item.group && (i === 0 || NAV[i - 1].group !== item.group) ? <span className="nav-group">{item.group}</span> : null}
              {!item.group && i > 0 ? <span className="nav-divider" aria-hidden="true" /> : null}
              <Link className="nav-link" href={item.href === "/historical" ? withBuild(item.href, build) : withPop(item.href, pop)} title={item.title}
                    aria-current={isCurrent(item.href, pathname) ? "page" : undefined} onClick={() => setOpen(false)}>
                <Icon name={item.icon} size={17}/><span>{item.label}{item.tag ? <> <small className="nav-tag">{item.tag}</small></> : null}</span>
              </Link>
            </li>
          ))}
        </ul>
        <div className="sidebar-foot"><span className="workspace-indicator"/><span>Local workspace<small>Fictional synthetic residents only</small></span></div>
      </nav>
      <div className="main">
        {historical ? <BuildBar /> : <PopulationBar />}
        <main id="main" className="content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
