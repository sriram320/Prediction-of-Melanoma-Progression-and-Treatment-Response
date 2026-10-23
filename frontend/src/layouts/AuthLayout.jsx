import Logo from "../components/Logo.jsx";
import TimelineVisual from "../components/TimelineVisual.jsx";

const PITCH = {
  hospital: {
    title: "Every visit, compared.",
    text: "Upload serial dermoscopy, let the model compare each visit with the last, and review the change before you sign.",
  },
  patient: {
    title: "Your skin checks, in one place.",
    text: "See your scan history and the reports your doctor has reviewed and released to you.",
  },
  admin: {
    title: "Platform administration.",
    text: "Manage hospitals, their administrators and model versions.",
  },
};

export default function AuthLayout({ variant = "hospital", children }) {
  const pitch = PITCH[variant];
  return (
    <div className="auth">
      <aside className="auth__aside">
        <Logo id="auth-brand-link" />
        <div className="auth__pitch">
          <h2>{pitch.title}</h2>
          <p>{pitch.text}</p>
          <div className="auth__visual"><TimelineVisual /></div>
        </div>
        <p className="auth__foot">AI decision support only. The final assessment is always made by the signing clinician.</p>
      </aside>
      <main className="auth__main">
        <div className="auth__card rise">{children}</div>
      </main>
    </div>
  );
}
