import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";

export default function NotFound() {
  return (
    <div className="stack">
      <PageHeader title="Page not found">
        The requested workbench route does not exist.
      </PageHeader>
      <section className="card stack">
        <p className="muted">Check the sidebar links or return to the workspace overview.</p>
        <div className="row">
          <Link className="button primary" href="/">Go to Overview</Link>
          <Link className="button" href="/experiments/new">New Experiment</Link>
          <Link className="button" href="/university">University Sim</Link>
        </div>
      </section>
    </div>
  );
}
