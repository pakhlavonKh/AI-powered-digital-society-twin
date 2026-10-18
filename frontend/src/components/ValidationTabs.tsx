"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { withBuild } from "@/lib/urls";

export function ValidationTabs() {
  const pathname = usePathname();
  const build = useSearchParams().get("build");
  return (
    <nav aria-label="Validation and data sources" className="row">
      <Link className="button small" href={withBuild("/historical/validation", build)} aria-current={pathname === "/validation" ? "page" : undefined}>Validation</Link>
      <Link className="button small" href={withBuild("/historical/data-sources", build)} aria-current={pathname === "/data-sources" ? "page" : undefined}>Data sources</Link>
    </nav>
  );
}
