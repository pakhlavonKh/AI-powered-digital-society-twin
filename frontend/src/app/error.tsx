"use client";

import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="stack">
      <PageHeader title="Something went wrong">
        An unexpected error interrupted rendering this workbench view.
      </PageHeader>
      <section className="card stack">
        <p className="small muted">{error.message || "Unexpected application error."}</p>
        <div className="row">
          <button type="button" className="button primary" onClick={reset}>Try again</button>
          <Link className="button" href="/">Return to Overview</Link>
        </div>
      </section>
    </div>
  );
}
