"use client";

import { useEffect, useState } from "react";

const NAMES = ["series-1", "series-2", "div-pos", "div-neg", "grid", "axis", "text-secondary", "text-muted", "surface-1", "surface-2"] as const;
export type ChartTokens = Record<(typeof NAMES)[number], string>;

const LIGHT_FALLBACK: ChartTokens = {
  "series-1": "#2a78d6", "series-2": "#eb6834", "div-pos": "#2a78d6", "div-neg": "#e34948", grid: "#e1e0d9",
  axis: "#c3c2b7", "text-secondary": "#52514e", "text-muted": "#67665f", "surface-1": "#fcfcfb", "surface-2": "#f3f2ef",
};

function read(): ChartTokens {
  const style = getComputedStyle(document.documentElement);
  const out = { ...LIGHT_FALLBACK };
  for (const name of NAMES) {
    const value = style.getPropertyValue(`--${name}`).trim();
    if (value) out[name] = value;
  }
  return out;
}

/** Resolves the CSS color roles to concrete values for SVG, and follows OS or explicit theme changes. */
export function useChartTokens(): ChartTokens {
  const [tokens, setTokens] = useState<ChartTokens>(LIGHT_FALLBACK);
  useEffect(() => {
    const update = () => setTokens(read());
    update();
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener?.("change", update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      media?.removeEventListener?.("change", update);
      observer.disconnect();
    };
  }, []);
  return tokens;
}
