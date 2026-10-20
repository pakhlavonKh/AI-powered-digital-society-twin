import type { Schemas } from "@/lib/api/client";
import { fmtValue } from "@/lib/format";

/** Label only when the trial's questionnaire snapshot lists it; otherwise the recorded code alone. */
export function AnswerCell({ answer, coercion }: { answer: Schemas["Answer"] | null | undefined; coercion?: Schemas["Coercion"] }) {
  if (!answer) return <span className="muted">No answer recorded</span>;
  return (
    <div>
      {answer.label ? <div>{answer.label}</div> : <div className="muted small">No label in the recorded questionnaire</div>}
      <code className="small">{fmtValue(answer.value)}</code>
      {coercion ? <div className="small muted">Recorded as <code>{fmtValue(coercion.recorded)}</code> after a lossless JSON-boolean coercion from <code>{fmtValue(coercion.original)}</code>.</div> : null}
      {answer.rationale ? <div className="small">Rationale: {answer.rationale}</div> : null}
      {answer.confidence !== null ? <div className="small muted">Confidence: {answer.confidence}</div> : null}
    </div>
  );
}
