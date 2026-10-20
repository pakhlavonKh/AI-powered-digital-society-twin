import type { Schemas } from "@/lib/api/client";
import { AnswerCell } from "../AnswerCell";
import { Badge } from "../StatusBadge";

/** Recorded JSON-boolean coercions per trial, keyed `label:question_id`. */
export function coercionMap(result: Schemas["Results"]): Map<string, Schemas["Coercion"]> {
  const out = new Map<string, Schemas["Coercion"]>();
  for (const t of result.trial_summaries) for (const c of t.coerced_answers) if (c.question_id) out.set(`${t.label}:${c.question_id}`, c);
  return out;
}

/** Saved answers of persona A and B side by side, exactly as recorded; nothing is re-asked or re-labelled. */
export function ComparisonTable({ result }: { result: Schemas["Results"] }) {
  const coercions = coercionMap(result);
  const [a, b] = result.trial_summaries;
  return (
    <div className="table-wrap">
      <table className="answers-table">
        <caption>Persona A {a?.persona_id ?? ""} versus persona B {b?.persona_id ?? ""}; one response each</caption>
        <thead><tr><th scope="col">Question</th><th scope="col">Persona A</th><th scope="col">Persona B</th><th scope="col">Same / different</th></tr></thead>
        <tbody>
          {result.comparison_rows.map((row) => (
            <tr key={row.question_id}>
              <th scope="row">{row.prompt ?? row.question_id}<div className="small muted"><code>{row.question_id}</code>{row.question_type ? ` · ${row.question_type}` : ""}</div></th>
              <td><AnswerCell answer={row.answer_a} coercion={a ? coercions.get(`${a.label}:${row.question_id}`) : undefined} /></td>
              <td><AnswerCell answer={row.answer_b} coercion={b ? coercions.get(`${b.label}:${row.question_id}`) : undefined} /></td>
              <td>{row.value_differs === null ? <span className="muted">–</span>
                : row.value_differs ? <Badge tone="info" glyph="≠">Different</Badge> : <Badge tone="neutral" glyph="=">Same</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
