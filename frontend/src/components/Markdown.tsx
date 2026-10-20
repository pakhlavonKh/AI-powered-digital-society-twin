"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders untrusted Markdown. Raw HTML is dropped (skipHtml) and react-markdown's URL filter stays on. */
export function SafeMarkdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}
