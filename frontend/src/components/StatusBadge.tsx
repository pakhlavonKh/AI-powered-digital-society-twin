import { HASH_STATES, RUN_STATES, statusInfo, TRIAL_STATES, type StatusInfo, type Tone } from "./status";

export function Badge({ tone, glyph, children, title }: { tone: Tone; glyph?: string; children: React.ReactNode; title?: string }) {
  return (
    <span className={`badge tone-${tone}`} title={title}>
      {glyph ? <span className="glyph" aria-hidden="true">{glyph}</span> : null}
      {children}
    </span>
  );
}

function InfoBadge({ info }: { info: StatusInfo }) {
  return <Badge tone={info.tone} glyph={info.glyph} title={info.description}>{info.label}</Badge>;
}

export function RunStateBadge({ state }: { state: string | null | undefined }) {
  return <InfoBadge info={statusInfo(RUN_STATES, state)} />;
}

export function TrialStateBadge({ state }: { state: string | null | undefined }) {
  return <InfoBadge info={statusInfo(TRIAL_STATES, state)} />;
}

export function HashBadge({ status }: { status: string }) {
  return <InfoBadge info={statusInfo(HASH_STATES, status)} />;
}

export function CheckBadge({ passed }: { passed: boolean }) {
  return passed ? <Badge tone="good" glyph="✓">Passed</Badge> : <Badge tone="crit" glyph="×">Not passed</Badge>;
}

/** Where the evidence came from. Whether it was a fake transport is shown by the state badge. */
export function OriginBadge({ origin }: { origin: string; evidenceKind?: string | null }) {
  return origin === "imported"
    ? <Badge tone="neutral" glyph="⧉">Imported historical</Badge>
    : <Badge tone="info" glyph="◆">Managed</Badge>;
}
