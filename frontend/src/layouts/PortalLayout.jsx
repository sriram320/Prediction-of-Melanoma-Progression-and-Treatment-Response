import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { ROLE_LABELS } from "../auth/roles.js";
import Icon from "../components/Icon.jsx";
import Logo from "../components/Logo.jsx";
import MockBanner from "../components/MockBanner.jsx";

// Navigation per role. `soon` marks items whose page is a placeholder for a later phase.
const NAV = {
  super_admin: [
    { to: "/admin", label: "Hospitals", icon: "hospital", end: true },
    { to: "/admin/models", label: "Model versions", icon: "model", soon: "P6" },
    { to: "/admin/audit", label: "Audit log", icon: "audit", soon: "P5" },
    { to: "/admin/account", label: "My account", icon: "user" },
  ],
  hospital_admin: [
    { to: "/hospital", label: "Dashboard", icon: "dashboard", end: true },
    { to: "/hospital/staff", label: "Staff", icon: "users" },
    { to: "/hospital/patients", label: "Patients", icon: "patients", soon: "P2" },
    { to: "/hospital/fairness", label: "Fairness report", icon: "scale", soon: "P5" },
    { to: "/hospital/audit", label: "Audit log", icon: "audit", soon: "P5" },
    { to: "/hospital/account", label: "My account", icon: "user" },
  ],
  doctor: [
    { to: "/doctor", label: "Worklist", icon: "clipboard", end: true },
    { to: "/doctor/patients", label: "Patients", icon: "patients", soon: "P2" },
    { to: "/doctor/reports", label: "Reports", icon: "report", soon: "P4" },
    { to: "/doctor/account", label: "My account", icon: "user" },
  ],
  technician: [
    { to: "/technician", label: "Patients", icon: "patients", end: true },
    { to: "/technician/uploads", label: "Uploads & jobs", icon: "upload", soon: "P3" },
    { to: "/technician/account", label: "My account", icon: "user" },
  ],
  patient: [
    { to: "/patient", label: "Overview", icon: "dashboard", end: true },
    { to: "/patient/lesions", label: "My scans", icon: "lesion", soon: "P2" },
    { to: "/patient/documents", label: "Documents", icon: "document", soon: "P2" },
    { to: "/patient/reports", label: "Reports", icon: "report", soon: "P4" },
    { to: "/patient/account", label: "My account", icon: "user" },
  ],
};

const PORTAL_NAME = {
  super_admin: "Platform console",
  hospital_admin: "Hospital admin",
  doctor: "Clinician portal",
  technician: "Technician portal",
  patient: "Patient portal",
};

export default function PortalLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => setNavOpen(false), [location.pathname]);

  const items = NAV[user.role] || [];
  const loginPath = user.role === "patient" ? "/patient/login" : user.role === "super_admin" ? "/admin/login" : "/hospital/login";

  async function handleLogout() {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      navigate(loginPath, { replace: true });
    }
  }

  return (
    <div className={`portal ${navOpen ? "is-nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar__brand"><Logo to={items[0]?.to || "/"} id="sidebar-brand-link" /></div>
        <div className="sidebar__portal">{PORTAL_NAME[user.role]}</div>
        <nav className="nav">
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="nav__link"
              id={`nav-${item.to.replaceAll("/", "-").replace(/^-/, "")}`}>
              <Icon name={item.icon} />
              {item.label}
              {item.soon && <span className="nav__soon" title={`Planned for phase ${item.soon}`}>{item.soon}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__user">
          <div className="sidebar__user-name">{user.full_name}</div>
          <div className="sidebar__user-meta">
            {ROLE_LABELS[user.role]}{user.hospital ? ` · ${user.hospital.code}` : ""}
          </div>
          <button type="button" className="btn btn--ghost btn--sm btn--block" style={{ marginTop: 10 }}
            onClick={handleLogout} disabled={signingOut} id="sidebar-logout-btn">
            <Icon name="logout" size={15} /> Sign out
          </button>
        </div>
      </aside>

      <div className="main">
        <div className="mobile-bar">
          <Logo to={items[0]?.to || "/"} id="mobile-brand-link" />
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setNavOpen((v) => !v)}
            aria-expanded={navOpen} aria-label="Toggle navigation" id="mobile-nav-toggle">
            <Icon name={navOpen ? "close" : "menu"} />
          </button>
        </div>
        <MockBanner />
        <main className="main__content rise" key={location.pathname}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
