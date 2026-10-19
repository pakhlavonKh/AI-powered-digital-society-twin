export const POPULATION_LABEL = "Synthetic population generated from official aggregate statistics (sources listed). No real individual records; not a census.";
export const RESPONSE_LABEL = "Synthetic personas and AI-generated responses. Not real people. Not a prediction of real behaviour.";

export function SyntheticNotice({ kind }: { kind: "population" | "responses" }) {
  return (
    <p className="notice synthetic" role="note">
      <strong>{kind === "population" ? "Synthetic data. " : "Synthetic responses. "}</strong>
      {kind === "population" ? POPULATION_LABEL : RESPONSE_LABEL}
    </p>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "warn" | "crit"; title?: string; children: React.ReactNode }) {
  return (
    <div className={`notice ${tone}`} role={tone === "crit" ? "alert" : "note"}>
      {title ? <strong>{title} </strong> : null}
      {children}
    </div>
  );
}
