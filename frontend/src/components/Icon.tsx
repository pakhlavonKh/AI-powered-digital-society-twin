import type { CSSProperties } from "react";

export function Icon({ name, size = 18, style }: { name: string; size?: number; style?: CSSProperties }) {
  const paths: Record<string, React.ReactNode> = {
    dashboard: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    population: <><circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v3"/></>,
    cohorts: <><circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20v-2a6 6 0 0 1 12 0v2m1-6a5 5 0 0 1 7 4v2"/></>,
    persona: <><circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></>,
    experiment: <><path d="m12 3 9 9-9 9-9-9Z"/><path d="M8 12h8m-4-4v8"/></>,
    results: <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10M7 12h6M7 16h3"/></>,
    validation: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
    sources: <><path d="M6 3h9l4 4v14H6Z"/><path d="M14 3v5h5M9 12h7M9 16h5"/></>,
    location: <><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
    network: <><path d="m4 5 8 7 8-7M4 19l8-7 8 7M12 3v18M3 12h18"/><circle cx="12" cy="12" r="3"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    globe: <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/></>,
    chart: <><path d="M4 3v17h17M8 16v-5m5 5V7m5 9V4"/></>,
    layers: <><path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"/></>,
    archive: <><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name] ?? paths.chart}</svg>;
}
