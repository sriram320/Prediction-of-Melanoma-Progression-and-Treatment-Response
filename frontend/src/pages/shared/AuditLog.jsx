import { Fragment, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { get, post, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { ROLE_LABELS } from "../../auth/roles.js";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import {
  Alert, Button, CopyButton, EmptyState, PageHeader, Pagination, Select, TextInput,
} from "../../components/ui.jsx";
import { ACTION_GROUPS, actionLabel, DETAIL_LABELS, ENTITY_LABELS } from "../../utils/audit.js";
import { errorMessage, formatDateTime, todayISO } from "../../utils/format.js";

const PAGE_SIZE = 50;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMPTY = { action: "", user_id: "", entity_id: "", from: "", to: "", hospital_id: "" };

function detailValue(v) {
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v ?? "–");
}

function InlineDetails({ details }) {
  const shown = Object.entries(details).filter(([k]) => DETAIL_LABELS[k]);
  if (!shown.length) return <span className="faint">–</span>;
  return (
    <span className="audit-details">
      {shown.slice(0, 3).map(([k, v]) => (
        <span key={k} className="audit-details__item"><span className="faint">{DETAIL_LABELS[k]}:</span> {detailValue(v)}</span>
      ))}
    </span>
  );
}

function ExpandedRow({ e, colSpan }) {
  return (
    <tr className="audit-table__expanded">
      <td colSpan={colSpan}>
        <dl className="dl-grid dl-grid--compact">
          {e.entity_id && (
            <div className="dl-grid__row"><dt>Subject id</dt>
              <dd className="mono">{e.entity_id} <CopyButton id={`audit-copy-${e.id}`} text={e.entity_id} /></dd></div>
          )}
          {Object.entries(e.details).map(([k, v]) => (
            <div key={k} className="dl-grid__row"><dt>{DETAIL_LABELS[k] || k}</dt><dd className="mono">{detailValue(v)}</dd></div>
          ))}
          <div className="dl-grid__row"><dt>Browser</dt><dd className="mono">{e.user_agent || "–"}</dd></div>
          <div className="dl-grid__row"><dt>Entry hash</dt><dd className="mono">{e.row_hash}</dd></div>
          <div className="dl-grid__row"><dt>Previous hash</dt><dd className="mono">{e.prev_hash || "– (first entry)"}</dd></div>
        </dl>
      </td>
    </tr>
  );
}

function VerifyChain() {
  const verify = useMutation({ mutationFn: () => post("/audit/verify") });
  const r = verify.data;
  return (
    <div className="stack stack--sm">
      <div className="row row--between">
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          Every entry stores the hash of the one before it, so an edited or deleted entry breaks the chain.
        </p>
        <Button variant="secondary" size="sm" id="audit-verify-btn" loading={verify.isPending} onClick={() => verify.mutate()}>
          <Icon name="shield" size={15} /> Verify hash chain
        </Button>
      </div>
      {verify.isError && <Alert kind="error">{errorMessage(verify.error)}</Alert>}
      {r && (r.ok ? (
        <Alert kind="success" id="audit-verify-result">
          Chain intact: {r.checked.toLocaleString("en-IN")} entries checked at {formatDateTime(r.verified_at)}.
          Newest entry #{r.head_id}, hash <span className="mono">{r.head_hash?.slice(0, 16)}…</span>. Keep a copy of this
          hash outside the server: removing the newest entries can only be detected against a saved head.
        </Alert>
      ) : (
        <Alert kind="error" id="audit-verify-result">
          The chain is broken: {r.hash_mismatches} edited, {r.missing_links} with a missing predecessor, {r.forks} duplicated
          link{r.forks === 1 ? "" : "s"}. First problem at entry #{r.first_problem_id}. Treat the log as tampered and
          investigate.
        </Alert>
      ))}
    </div>
  );
}

export default function AuditLog() {
  const { user } = useAuth();
  const platform = user.role === "super_admin";
  const [draft, setDraft] = useState(EMPTY);
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  const actions = useQuery({ queryKey: ["audit", "actions"], queryFn: () => get("/audit/actions") });
  const staff = useQuery({
    queryKey: ["hospital", "staff", "all"], queryFn: () => get("/hospital/staff?page_size=100"), enabled: !platform,
  });
  const hospitals = useQuery({
    queryKey: ["admin", "hospitals", "all"], queryFn: () => get("/admin/hospitals?page_size=100"), enabled: platform,
  });
  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["audit", filters, page],
    queryFn: () => get(`/audit${qs({ ...filters, page, page_size: PAGE_SIZE })}`),
    placeholderData: (prev) => prev,
  });

  const entityInvalid = draft.entity_id.trim() !== "" && !UUID_RE.test(draft.entity_id.trim());
  const apply = (e) => {
    e.preventDefault();
    if (entityInvalid) return;
    setFilters({ ...draft, entity_id: draft.entity_id.trim() });
    setPage(1);
    setOpen(null);
  };
  const groups = [...new Set((actions.data || []).map((a) => a.split(".")[0]))];
  const actionOptions = [{ value: "", label: "All actions" }];
  for (const g of groups) {
    actionOptions.push({ value: g, label: `${ACTION_GROUPS[g] || g} (all)` });
    for (const a of actions.data.filter((x) => x.startsWith(`${g}.`))) {
      actionOptions.push({ value: a, label: `   ${actionLabel(a)}` });
    }
  }
  const cols = platform ? 7 : 6;

  return (
    <>
      <PageHeader eyebrow={platform ? "All hospitals" : user.hospital?.name} title="Audit log"
        subtitle="Every sign-in, file access, AI result, review, signature and release, newest first. Entries cannot be changed or deleted." />
      <div className="stack stack--lg">
        {platform && <div className="card"><VerifyChain /></div>}

        <form className="card filter-bar" onSubmit={apply} role="search" aria-label="Filter the audit log" noValidate>
          <div className="filter-bar__fields">
            <Select id="audit-action" label="Action" value={draft.action} onChange={set("action")} options={actionOptions} />
            {platform ? (
              <Select id="audit-hospital" label="Hospital" value={draft.hospital_id} onChange={set("hospital_id")}
                options={[{ value: "", label: "All hospitals" },
                  ...(hospitals.data?.items || []).map((h) => ({ value: h.id, label: `${h.name} (${h.code})` }))]} />
            ) : (
              <Select id="audit-user" label="Person" value={draft.user_id} onChange={set("user_id")}
                options={[{ value: "", label: "Anyone" },
                  ...(staff.data?.items || []).map((s) => ({ value: s.id, label: `${s.full_name} (${ROLE_LABELS[s.role]})` }))]} />
            )}
            <TextInput id="audit-from" label="From" type="date" value={draft.from} max={draft.to || todayISO()} onChange={set("from")} />
            <TextInput id="audit-to" label="To" type="date" value={draft.to} min={draft.from || undefined} max={todayISO()} onChange={set("to")} />
            <TextInput id="audit-entity" label="Subject id" value={draft.entity_id} onChange={set("entity_id")}
              placeholder="e.g. a report or AI result id" error={entityInvalid ? "Paste a full id (UUID)" : undefined} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Button type="submit" size="sm" id="audit-apply-btn"><Icon name="search" size={15} /> Apply</Button>
            <Button variant="ghost" size="sm" id="audit-reset-btn"
              onClick={() => { setDraft(EMPTY); setFilters(EMPTY); setPage(1); }}>Clear</Button>
          </div>
        </form>

        {isLoading ? <PageLoading /> : isError ? <Alert kind="error">{errorMessage(error)}</Alert> : (
          <div className={`card card--flush ${isFetching ? "is-refreshing" : ""}`}>
            {data.items.length === 0 ? (
              <EmptyState icon="audit" title="No entries match"><p>Try a wider date range or clear the filters.</p></EmptyState>
            ) : (
              <div className="table-wrap">
                <table className="table table--compact audit-table" id="audit-table">
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      {platform && <th scope="col">Hospital</th>}
                      <th scope="col">Who</th>
                      <th scope="col">Action</th>
                      <th scope="col">Subject</th>
                      <th scope="col">Details</th>
                      <th scope="col">IP address</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((e) => (
                      <Fragment key={e.id}>
                        <tr className={`audit-table__row ${open === e.id ? "is-open" : ""}`}>
                          <td className="nowrap">
                            <button type="button" className="link-btn" id={`audit-row-${e.id}`} aria-expanded={open === e.id}
                              onClick={() => setOpen(open === e.id ? null : e.id)}>
                              {formatDateTime(e.occurred_at)}
                            </button>
                          </td>
                          {platform && <td>{e.hospital_code || <span className="faint">Platform</span>}</td>}
                          <td>
                            <div>{e.actor_name || (e.role === "patient" ? "A patient" : e.role ? ROLE_LABELS[e.role] : "System")}</div>
                            {e.role && e.actor_name && <div className="faint" style={{ fontSize: "0.8rem" }}>{ROLE_LABELS[e.role]}</div>}
                          </td>
                          <td className={e.action === "auth.login_failed" ? "audit-table__warn" : undefined}>
                            {e.action === "auth.login_failed" && <Icon name="alert" size={14} />} {actionLabel(e.action)}
                          </td>
                          <td>{e.entity_type ? (
                            <span>{ENTITY_LABELS[e.entity_type] || e.entity_type} <span className="mono faint">{e.entity_id?.slice(0, 8)}</span></span>
                          ) : <span className="faint">–</span>}</td>
                          <td><InlineDetails details={e.details} /></td>
                          <td className="mono faint">{e.ip || "–"}</td>
                        </tr>
                        {open === e.id && <ExpandedRow e={e} colSpan={cols} />}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pagination id="audit-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </div>
        )}
        {platform && (
          <p className="faint" style={{ fontSize: "0.85rem" }}>
            Free-text reasons are hidden here and patients are not named. Each hospital's administrators see them in
            their own audit log.
          </p>
        )}
      </div>
    </>
  );
}
