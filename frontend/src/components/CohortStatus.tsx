import { Badge } from "./StatusBadge";

export function CohortStatusBadge({ status }: { status: string }) {
  if (status === "valid") return <Badge tone="good" glyph="✓">Source unchanged</Badge>;
  if (status === "source_changed") return <Badge tone="crit" glyph="!">Source changed</Badge>;
  return <Badge tone="crit" glyph="!">Build unavailable</Badge>;
}

export function FilterChips({ filters }: { filters: Record<string, string[]> }) {
  const entries = Object.entries(filters);
  if (!entries.length) return <span className="muted">No filters (all residents)</span>;
  return (
    <span className="row" style={{ gap: 6 }}>
      {entries.map(([k, values]) => <span className="chip" key={k}><strong>{k}:</strong> {values.join(" or ")}</span>)}
    </span>
  );
}
