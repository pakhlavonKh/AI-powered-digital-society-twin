import type { Schemas } from "@/lib/api/client";
import { fmtInt, fmtUsd } from "@/lib/format";

type Usage = Schemas["Usage"] | null | undefined;

function costCell(usage: Usage) {
  if (!usage || usage.cost_usd === null) return "unknown";
  return `${fmtUsd(usage.cost_usd)}${usage.cost_source === "estimated" ? " (estimated)" : usage.cost_source ? ` (${usage.cost_source})` : " (source unknown)"}`;
}

/** Null means unknown and is never shown as zero. Estimated cost is never presented as billed cost. */
export function UsageTable({ rows, caption }: { rows: { label: string; usage: Usage }[]; caption: string }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Scope</th>
            <th scope="col" className="num">Input tokens</th>
            <th scope="col" className="num">Output tokens</th>
            <th scope="col" className="num">Cache tokens</th>
            <th scope="col" className="num">Cost (USD)</th>
            <th scope="col">Billed amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, usage }) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td className="num">{fmtInt(usage?.n_input_tokens)}</td>
              <td className="num">{fmtInt(usage?.n_output_tokens)}</td>
              <td className="num">{fmtInt(usage?.n_cache_tokens)}</td>
              <td className="num">{costCell(usage)}</td>
              <td>{usage?.billed_cost_usd === null || usage?.billed_cost_usd === undefined ? "Not recorded" : fmtUsd(usage.billed_cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
