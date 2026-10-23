import { Link } from "react-router-dom";

export function LogoMark({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="hsl(222 40% 12%)" stroke="hsl(186 80% 48% / 0.45)" />
      <circle cx="16" cy="16" r="10" fill="none" stroke="hsl(186 85% 56%)" strokeWidth="1.6" strokeDasharray="3 2.2" />
      <circle cx="16" cy="16" r="5.2" fill="hsl(186 85% 56%)" />
    </svg>
  );
}

export default function Logo({ to = "/", id = "brand-home-link" }) {
  return (
    <Link to={to} className="brand" id={id} aria-label="MelanoTrack home">
      <LogoMark />
      <span className="brand__name">Melano<span>Track</span></span>
    </Link>
  );
}
