// Basic UI primitives. Every interactive element takes an explicit, unique `id`.
import { useEffect, useId, useRef, useState } from "react";
import Icon from "./Icon.jsx";

export function Button({ variant = "primary", size, block, loading, children, className = "", type = "button", ...rest }) {
  const cls = ["btn", `btn--${variant}`, size === "sm" && "btn--sm", block && "btn--block", className]
    .filter(Boolean).join(" ");
  return (
    <button type={type} className={cls} disabled={loading || rest.disabled} aria-busy={loading || undefined} {...rest}>
      {loading && <span className="btn__spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Field({ id, label, hint, error, children }) {
  return (
    <div className="field">
      {label && <label className="field__label" htmlFor={id}>{label}</label>}
      {children}
      {error ? <span className="field__error" id={`${id}-error`}>{error}</span>
        : hint ? <span className="field__hint" id={`${id}-hint`}>{hint}</span> : null}
    </div>
  );
}

export function TextInput({ id, label, hint, error, className = "", ...rest }) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <input id={id} className={`input ${className}`} aria-invalid={error ? "true" : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined} {...rest} />
    </Field>
  );
}

export function Select({ id, label, hint, error, options, ...rest }) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <select id={id} className="select" aria-invalid={error ? "true" : undefined} {...rest}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
}

const ALERT_ICONS = { error: "alert", warning: "alert", success: "check", info: "info" };

export function Alert({ kind = "info", children, id }) {
  if (!children) return null;
  return (
    <div className={`alert alert--${kind}`} role={kind === "error" ? "alert" : "status"} id={id}>
      <Icon name={ALERT_ICONS[kind]} className="alert__icon" size={16} />
      <div>{children}</div>
    </div>
  );
}

export function Badge({ kind, dot, children }) {
  return <span className={["badge", kind && `badge--${kind}`, dot && "badge--dot"].filter(Boolean).join(" ")}>{children}</span>;
}

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <div className="page-header__eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p className="page-header__sub">{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Spinner({ label = "Loading" }) {
  return <div className="spinner" role="status" aria-label={label} />;
}

export function StatCard({ label, value, note, tone }) {
  return (
    <div className={["card", "stat", tone && `stat--${tone}`].filter(Boolean).join(" ")}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value ?? "–"}</div>
      {note && <div className="stat__note">{note}</div>}
    </div>
  );
}

export function EmptyState({ icon = "info", title, children }) {
  return (
    <div className="empty">
      <div className="empty__icon"><Icon name={icon} size={24} /></div>
      <h3 className="empty__title">{title}</h3>
      {children}
    </div>
  );
}

/** Placeholder for features scheduled in a later roadmap phase. */
export function ComingSoon({ phase, title, items = [], icon = "timeline" }) {
  return (
    <div className="card">
      <EmptyState icon={icon} title={title}>
        <p>Scheduled for phase <strong>{phase}</strong> of the build plan.</p>
        {items.length > 0 && <ul className="empty__list">{items.map((i) => <li key={i}>{i}</li>)}</ul>}
      </EmptyState>
    </div>
  );
}

export function Modal({ id, title, onClose, children, footer, dismissible = true }) {
  const titleId = useId();
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = dismissible ? onClose : null;
  useEffect(() => {
    // Runs once per open: focus the first field, close on Escape, restore focus on unmount.
    const prev = document.activeElement;
    const first = ref.current?.querySelector("input, select, textarea, button:not([data-close])");
    (first || ref.current)?.focus();
    const onKey = (e) => e.key === "Escape" && closeRef.current?.();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && dismissible && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} id={id} ref={ref} tabIndex={-1}>
        <div className="modal__header">
          <h2 id={titleId}>{title}</h2>
          {dismissible && (
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close dialog"
              id={`${id}-close`} data-close>
              <Icon name="close" />
            </button>
          )}
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__footer">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ id, title, children, confirmLabel = "Confirm", danger, loading, onConfirm, onCancel }) {
  return (
    <Modal id={id} title={title} onClose={onCancel}
      footer={<>
        <Button variant="secondary" onClick={onCancel} id={`${id}-cancel`}>Cancel</Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading} id={`${id}-confirm`}>
          {confirmLabel}
        </Button>
      </>}>
      <div className="muted">{children}</div>
    </Modal>
  );
}

export function CopyButton({ id, text }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button variant="secondary" size="sm" id={id} onClick={async () => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      } catch { /* clipboard blocked: the value is still visible to copy by hand */ }
    }}>
      <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Copied" : "Copy"}
    </Button>
  );
}

/** Shows a one-time secret (temporary password, invite code). It is never retrievable again. */
export function SecretDialog({ id, title, label, secret, note, onClose }) {
  return (
    <Modal id={id} title={title} onClose={onClose} dismissible={false}
      footer={<Button onClick={onClose} id={`${id}-done`}>I have saved it</Button>}>
      <div className="stack">
        <p className="muted">{label}</p>
        <div className="secret-box">
          <code id={`${id}-value`}>{secret}</code>
          <CopyButton id={`${id}-copy`} text={secret} />
        </div>
        <Alert kind="warning">{note || "This is shown only once. Share it securely; it cannot be viewed again."}</Alert>
      </div>
    </Modal>
  );
}

export function Pagination({ id, page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="row row--between" style={{ padding: "12px 16px" }}>
      <span className="faint">Page {page} of {pages} · {total} total</span>
      <div className="row">
        <Button variant="secondary" size="sm" id={`${id}-prev`} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button variant="secondary" size="sm" id={`${id}-next`} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
