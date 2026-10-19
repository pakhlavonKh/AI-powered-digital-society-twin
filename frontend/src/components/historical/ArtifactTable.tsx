"use client";

import { useState } from "react";
import type { Schemas } from "@/lib/api/client";
import { fmtInt } from "@/lib/format";
import { apiPath } from "@/lib/urls";
import { SafeMarkdown } from "../Markdown";
import { Badge } from "../StatusBadge";

function ArtifactRow({ artifact }: { artifact: Schemas["Artifact"] }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const href = apiPath(`/artifacts/${artifact.artifact_id}`);
  const isMarkdown = artifact.media_type.startsWith("text/markdown");
  return (
    <tr>
      <th scope="row"><code>{artifact.relpath}</code>{artifact.caveat ? <div className="small muted">{artifact.caveat}</div> : null}
        {preview !== null ? <div className="card" style={{ marginTop: 8 }}><SafeMarkdown text={preview} /></div> : null}
        {failed ? <div className="small">Could not load the preview.</div> : null}
      </th>
      <td>{artifact.kind === "report" ? <Badge tone="warn" glyph="!">Descriptive report</Badge> : artifact.kind}</td>
      <td className="num">{fmtInt(artifact.size)} B</td>
      <td>
        <div className="row">
          <a className="button small" href={`${href}?download=true`} download>Download</a>
          {isMarkdown ? (
            <button type="button" className="button small" onClick={async () => {
              if (preview !== null) { setPreview(null); return; }
              try {
                const res = await fetch(href);
                if (!res.ok) throw new Error(String(res.status));
                setPreview(await res.text());
              } catch {
                setFailed(true);
              }
            }}>{preview !== null ? "Hide preview" : "Preview"}</button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

/** Files in a recorded run folder, served by server-owned IDs (read-only). */
export function ArtifactTable({ artifacts }: { artifacts: Schemas["Artifact"][] }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>Files in the run folder, served by server-owned IDs</caption>
        <thead><tr><th scope="col">File</th><th scope="col">Kind</th><th scope="col" className="num">Size</th><th scope="col">Actions</th></tr></thead>
        <tbody>{artifacts.map((art) => <ArtifactRow key={art.artifact_id} artifact={art} />)}</tbody>
      </table>
    </div>
  );
}
