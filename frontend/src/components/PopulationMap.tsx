"use client";

import Link from "next/link";
import { TURKEY_PROVINCES } from "@/lib/turkey-provinces";
import { fmtInt } from "@/lib/format";
import { Icon } from "./Icon";

export function PopulationMap({ province, year, count, href }: { province: string; year: number; count: number; href: string }) {
  const known = TURKEY_PROVINCES.some((p) => p.name === province);
  return <section className="population-map" aria-label="Geographic scope of the loaded population">
    <div className="map-heading"><span><Icon name="globe" size={15}/> Population coverage</span><span className="map-live"><i/> Loaded dataset</span></div>
    <div className="map-canvas">
      <svg viewBox="0 0 900 410" role="img" aria-label={`Türkiye province boundaries. ${known ? province : "No mapped province"} has loaded data; other provinces have no loaded data.`}>
        <defs><linearGradient id="province-fill" x2="0" y2="1"><stop stopColor="#3865a4"/><stop offset="1" stopColor="#254674"/></linearGradient><filter id="map-glow"><feGaussianBlur stdDeviation="3"/></filter></defs>
        <g className="map-reflection" transform="translate(0 693) scale(1 -1)">{TURKEY_PROVINCES.map((p) => <path key={p.iso} d={p.path}/>)}</g>
        <g className="province-shapes">{[...TURKEY_PROVINCES.filter(p=>p.name!==province),...TURKEY_PROVINCES.filter(p=>p.name===province)].map((p) => <path key={p.iso} d={p.path} className={p.name === province ? "province loaded" : "province"}><title>{p.name}: {p.name === province ? `${fmtInt(count)} loaded synthetic residents` : "no loaded data"}</title></path>)}</g>
      </svg>
      <div className="map-tooltip"><strong><Icon name="location" size={16}/>{province}</strong><span>Synthetic residents · {year}</span><b>{fmtInt(count)}</b><span>{known ? "Selected population build" : "Province not mapped"}</span><Link href={href}>Explore population <Icon name="arrow" size={13}/></Link></div>
      <div className="map-compass" aria-hidden="true">N<span>✦</span></div>
    </div>
    <div className="map-footer"><div className="legend"><span><i className="legend-key" style={{background:"#28d7c0"}}/>Loaded data</span><span><i className="legend-key" style={{background:"#315588"}}/>No loaded data</span></div><a href="/map-attribution.md" target="_blank" rel="noreferrer">Map attribution ↗</a></div>
  </section>;
}
