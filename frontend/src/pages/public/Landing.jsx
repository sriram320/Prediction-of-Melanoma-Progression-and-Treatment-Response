import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import Icon from "../../components/Icon.jsx";
import Logo from "../../components/Logo.jsx";
import TimelineVisual from "../../components/TimelineVisual.jsx";

const STEPS = [
  { title: "Capture every visit", text: "Technicians upload dermoscopic images of the same lesion at each follow-up, linked by date." },
  { title: "Compare over time", text: "The model aligns the visits and measures how size, colour and texture have changed." },
  { title: "Doctor reviews", text: "A dermatologist checks the explanation, confirms or overrides the result and signs the report." },
  { title: "Patient is informed", text: "Only signed, released reports reach the patient portal, written in plain language." },
];

const PRINCIPLES = [
  { icon: "alert", tone: "var(--referral)", bg: "var(--referral-soft)", title: "Unsure means refer",
    text: "When the model is not confident, it gives no category and asks for a dermatologist's review instead." },
  { icon: "user", tone: "var(--accent-strong)", bg: "var(--accent-soft)", title: "A clinician signs every report",
    text: "The AI supports the decision. The final assessment always belongs to the signing doctor." },
  { icon: "lock", tone: "var(--routine)", bg: "var(--routine-soft)", title: "Private and accountable",
    text: "Files are encrypted at rest, every hospital sees only its own patients, and every action is audited." },
];

export default function Landing() {
  const { user } = useAuth();
  return (
    <div className="landing">
      <nav className="landing__nav" aria-label="Site">
        <Logo id="landing-brand-link" />
        <div className="row">
          {user ? (
            <Link to={HOME_BY_ROLE[user.role]} className="btn btn--primary btn--sm" id="landing-open-portal">
              Open my portal
            </Link>
          ) : (
            <>
              <Link to="/patient/login" className="btn btn--ghost btn--sm" id="landing-nav-patient">Patient sign in</Link>
              <Link to="/hospital/login" className="btn btn--secondary btn--sm" id="landing-nav-hospital">Hospital sign in</Link>
            </>
          )}
        </div>
      </nav>

      <section className="landing__hero">
        <div className="rise">
          <h1>See how a lesion <span>changes</span>, not just how it looks.</h1>
          <p className="landing__lead">
            MelanoTrack compares dermoscopic images of the same lesion across visits to flag early signs of
            melanoma progression, with an explanation for every result and a dermatologist in the loop.
          </p>
          <div className="landing__ctas">
            <Link to="/hospital/login" className="btn btn--primary" id="landing-cta-hospital">
              <Icon name="hospital" /> Hospital staff sign in
            </Link>
            <Link to="/patient/login" className="btn btn--secondary" id="landing-cta-patient">
              <Icon name="user" /> Patient sign in
            </Link>
          </div>
          <p className="faint" style={{ marginTop: 16, fontSize: "0.85rem" }}>
            Received an invite code from your hospital? <Link to="/patient/activate" id="landing-activate-link">Activate your account</Link>.
          </p>
        </div>
        <div className="card hero-visual rise" aria-hidden="false">
          <div className="row row--between" style={{ marginBottom: 8 }}>
            <span className="faint" style={{ fontSize: "0.8rem" }}>Lesion L-03 · left shoulder</span>
            <span className="badge badge--shortened badge--dot">Example only</span>
          </div>
          <TimelineVisual />
        </div>
      </section>

      <section className="landing__section" aria-labelledby="how-heading">
        <h2 id="how-heading">How it works</h2>
        <p className="muted">The "E" in the ABCDE rule is evolution, and that is something a single photograph cannot show.</p>
        <div className="steps">
          {STEPS.map((s, i) => (
            <div className="card step" key={s.title}>
              <div className="step__num">{i + 1}</div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="landing__section" aria-labelledby="safety-heading">
        <h2 id="safety-heading">Built safety-first</h2>
        <div className="principles">
          {PRINCIPLES.map((p) => (
            <div className="card" key={p.title}>
              <div className="principle__icon" style={{ background: p.bg, color: p.tone }}><Icon name={p.icon} size={20} /></div>
              <h3 style={{ marginBottom: 6 }}>{p.title}</h3>
              <p className="muted" style={{ fontSize: "0.9rem" }}>{p.text}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="landing__footer">
        <div className="landing__footer-inner">
          <span>
            Research prototype: Longitudinal Multimodal AI for Early Prediction of Melanoma Progression.
            AI decision support only, not a diagnosis.
          </span>
          <Link to="/admin/login" className="faint" id="landing-admin-link">Platform admin</Link>
        </div>
      </footer>
    </div>
  );
}
