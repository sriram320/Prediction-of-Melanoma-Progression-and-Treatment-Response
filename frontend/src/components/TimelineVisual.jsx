// Decorative illustration: one lesion across four visits, the core idea of the product.
const VISITS = [
  { x: 60, r: 16, label: "Jan", fill: "hsl(28 45% 42%)" },
  { x: 160, r: 18, label: "Apr", fill: "hsl(25 48% 36%)" },
  { x: 260, r: 22, label: "Jul", fill: "hsl(20 50% 30%)" },
  { x: 360, r: 27, label: "Oct", fill: "hsl(15 52% 25%)" },
];

export default function TimelineVisual() {
  return (
    <svg viewBox="0 0 420 200" width="100%" role="img" aria-label="Illustration of a lesion compared across four visits">
      <defs>
        <radialGradient id="tv-skin" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="hsl(25 40% 70%)" />
          <stop offset="100%" stopColor="hsl(25 35% 58%)" />
        </radialGradient>
      </defs>
      <line x1="40" y1="150" x2="380" y2="150" stroke="hsl(220 24% 32%)" strokeWidth="2" />
      {VISITS.map((v, i) => (
        <g key={v.label}>
          <circle cx={v.x} cy="80" r="40" fill="url(#tv-skin)" opacity="0.92" />
          <ellipse cx={v.x} cy="80" rx={v.r} ry={v.r * 0.86} fill={v.fill} />
          {i > 0 && (
            <ellipse cx={v.x} cy="80" rx={VISITS[0].r} ry={VISITS[0].r * 0.86} fill="none"
              stroke="hsl(186 85% 60%)" strokeWidth="1.5" strokeDasharray="3 3" />
          )}
          <circle cx={v.x} cy="150" r="5" fill={i === VISITS.length - 1 ? "hsl(8 82% 64%)" : "hsl(186 80% 48%)"} />
          <text x={v.x} y="176" textAnchor="middle" fill="hsl(215 20% 72%)" fontSize="12" fontFamily="Inter">
            {v.label}
          </text>
        </g>
      ))}
      <text x="360" y="30" textAnchor="middle" fill="hsl(8 82% 70%)" fontSize="11" fontWeight="600" fontFamily="Inter">
        +184% area
      </text>
    </svg>
  );
}
