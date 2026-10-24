export function Ring({ score, size = 46 }: { score: number; size?: number }) {
  const s = Math.max(0, Math.min(100, Math.round(score)));
  const color = s < 50 ? "var(--muted)" : "var(--accent)";
  return (
    <svg className="ring" width={size} height={size} viewBox="0 0 46 46" role="img" aria-label={`совпадение ${s}%`}>
      <circle cx="23" cy="23" r="19" fill="none" stroke="var(--ring-track)" strokeWidth="3.2" />
      <circle cx="23" cy="23" r="19" fill="none" stroke={color} strokeWidth="3.2" strokeLinecap="round" pathLength={100}
        strokeDasharray={`${s} 100`} transform="rotate(-90 23 23)" />
      <text x="23" y="27.5" textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--fg)" fontFamily="Golos Text, Arial, sans-serif"
        style={{ fontVariantNumeric: "tabular-nums" }}>{s}</text>
    </svg>
  );
}
