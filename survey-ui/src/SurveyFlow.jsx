import React, { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

/* =========================
   API base resolution
========================= */
const FROM_VITE =
  (typeof import.meta !== "undefined" &&
    import.meta.env &&
    (import.meta.env.VITE_API_BASE ||
      import.meta.env.VITE_BACKEND ||
      import.meta.env.PUBLIC_API_BASE)) ||
  null;
const FROM_NODE =
  (typeof process !== "undefined" &&
    process.env &&
    (process.env.VITE_API_BASE ||
      process.env.REACT_APP_API_BASE ||
      process.env.API_BASE)) ||
  null;
const API_BASE = FROM_VITE || FROM_NODE || "http://localhost:8000";

/* =========================
   URL helpers
========================= */
function readLinkTokenFromURL() {
  try {
    const sp = new URLSearchParams(window.location.search);
    return sp.get("token") || sp.get("t") || null;
  } catch {
    return null;
  }
}

/* =========================
   Demo fallback
========================= */
/** @typedef {import('./types').Block} Block */
const demoBlocks = /** @type {any[]} */ ([
  { id: "profile", name: "Personal Information & Subject", type: "profile", requireContactAtLeastOne: true },
  { id: "b1", name: "Ваша удовлетворённость этим фронтендом", type: "rating", question: "Как оцениваете?", min: 1, max: 10 },
  { id: "b2", name: "Тон цвета (опционально)", type: "rating", question: "Тон цвета оцените от 1 до 10", min: 1, max: 10, optional: true },
  { id: "b3", name: "Если есть что добавить (опционально)", type: "text", prompt: "Расскажите что угодно, чем ещё хочется поделиться", placeholder: "Писать здесь...", minLength: 1, optional: true },
]);
const demoRespondent = { firstName: "Jane", lastName: "Doe", email: "jane@example.com", telegram: "jane_d" };
const demoSubject = { firstName: "John", lastName: "Smith" };
const demoDeadlineISO = "2099-12-31T23:59:59Z";

const LS_KEY = "surveyflow_answers_v1";

/* =========================
   Pure helpers
========================= */
function isEmailValid(email) {
  if (!email) return false;
  return /.+@.+\..+/.test(email);
}

/** ceil days (can be negative if past) */
function daysLeft(deadlineISO) {
  if (!deadlineISO) return Infinity;
  const now = Date.now();
  const end = Date.parse(deadlineISO);
  if (Number.isNaN(end)) return Infinity;
  const ms = end - now;
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

/** Validate a block given current answers */
function isBlockValidForAnswers(b, answers) {
  if (!b) return false;
  if (b.type === "rating") {
    const v = answers[b.id];
    if (b.optional && (v === undefined || v === null)) return true;
    return typeof v === "number" && v >= (b.min ?? 1) && v <= (b.max ?? 10);
  }
  if (b.type === "text") {
    const tRaw = answers[b.id] ?? "";
    const t = String(tRaw).trim();
    if (b.optional && t.length === 0) return true;
    const min = b.minLength ?? 0;
    return t.length >= min;
  }
  if (b.type === "profile") {
    const v = answers[b.id] || {};
    const first = (v.firstName || "").trim();
    const last = (v.lastName || "").trim();
    const email = (v.email || "").trim();
    const tg = (v.telegram || "").trim();
    const hasNames = first.length > 0 && last.length > 0;
    const hasContact = isEmailValid(email) || tg.length > 0;
    return hasNames && hasContact;
  }
  return false;
}

export default function SurveyFlow({
  blocks: blocksProp = demoBlocks,
  deadlineISO: deadlineISOProp = demoDeadlineISO,
  respondent: respondentProp = demoRespondent,
  subject: subjectProp = demoSubject,
  apiBase = API_BASE,
  linkToken: linkTokenProp = null,
}) {
  const linkToken = linkTokenProp ?? readLinkTokenFromURL();

  /* ================
     Local state
  ================= */
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState(() => {
    const raw = typeof window !== "undefined" ? localStorage.getItem(LS_KEY) : null;
    return raw ? JSON.parse(raw) : {};
  });
  const [baseline, setBaseline] = useState({}); // answers coming from server (for PATCH delta calc)
  const [visited, setVisited] = useState(() => Array(blocksProp.length).fill(false));
  const [submitted, setSubmitted] = useState(false);

  const [server, setServer] = useState({
    surveyId: null,
    responseId: null, // if existing submission found
    version: null,
  });

  const [meta, setMeta] = useState({
    loading: !!linkToken,
    error: null,
    hasServerAnswers: false, // true if any block has answerText
    isClosedServer: false,   // from /access
  });

  const [runtime, setRuntime] = useState({
    deadlineISO: deadlineISOProp,
    respondent: respondentProp,
    subject: subjectProp,
    blocks: blocksProp,
  });

  const startedAtRef = useRef(new Date());

  /* ================
     Derived helpers
  ================= */
  const metaKey = (sid) => (sid ? `surveyflow_meta_${sid}` : null);

  function computeStartIndex(blocks, ans) {
    for (let i = 0; i < blocks.length; i++) {
      if (!isBlockValidForAnswers(blocks[i], ans)) return i;
    }
    return Math.max(0, blocks.length - 1);
  }

  function allBlocksValid(blocks, ans) {
    return blocks.every((b) => isBlockValidForAnswers(b, ans));
  }

  function resetAll() {
    try {
      if (typeof window !== "undefined") localStorage.removeItem(LS_KEY);
    } catch {}
    try {
      const mk = metaKey(server.surveyId);
      if (mk) localStorage.removeItem(mk);
    } catch {}

    const prof = runtime.blocks.find((b) => b.type === "profile");
    const base = prof ? { [prof.id]: { ...runtime.respondent } } : {};
    setAnswers(base);
    setBaseline({});
    setVisited(Array.from({ length: runtime.blocks.length }, (_, i) => i === 0));
    setSubmitted(false);
    setCurrent(0);
    setServer((s) => ({ ...s, responseId: null, version: null }));
    setMeta((m) => ({ ...m, hasServerAnswers: false }));
  }

  // Prefer server-closed over deadline calc
  const dLeft = daysLeft(runtime.deadlineISO);
  const isClosedByDeadline = Number.isFinite(dLeft) && dLeft <= 0;
  const isClosed = meta.isClosedServer || isClosedByDeadline;

  /* ================
     Prefill profile
  ================= */
  useEffect(() => {
    const prof = runtime.blocks.find((b) => b.type === "profile");
    if (prof && !answers[prof.id]) {
      setAnswers((prev) => ({ ...prev, [prof.id]: { ...runtime.respondent } }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ================
     Persist answers
  ================= */
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(answers));
    } catch {}
  }, [answers]);

  /* ================
     Visited tracking
  ================= */
  useEffect(() => {
    setVisited((prev) => {
      const next = [...prev];
      next[current] = true;
      return next;
    });
  }, [current]);

  /* ================
     Keyboard nav
  ================= */
  useEffect(() => {
    if (isClosed) return;
    const onKey = (e) => {
      if (e.key === "ArrowLeft") setCurrent((i) => Math.max(0, i - 1));
      else if (e.key === "ArrowRight") handleNext();
      else if (e.key === "Enter") {
        if (isCurrentValid()) handleNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Shift+R to reset
  useEffect(() => {
    const onKey = (e) => {
      if ((e.key === "R" || e.key === "r") && e.shiftKey) {
        e.preventDefault();
        resetAll();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ?reset=1
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      if (sp.get("reset") === "1") resetAll();
    } catch {}
  }, []);

  /* ================
     Load /access
  ================= */
  useEffect(() => {
    if (!linkToken) return; // demo mode
    let cancelled = false;

    (async () => {
      try {
        setMeta((m) => ({ ...m, loading: true, error: null }));

        const res = await fetch(`${apiBase}/v1/surveys/access/${linkToken}`);
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(`${res.status} ${res.statusText}${text ? ` — ${text}` : ""}`);
        }
        const env = await res.json();
        const srv = env.survey;
        // NEW: pick up existing response meta from backend
        const rid = env?.response?.responseId ?? null;
        const ver = env?.response?.version ?? null;

        // keep whatever you already set, just ensure these are present
        setServer((s) => ({
          ...s,
          surveyId: srv.surveyId,
          responseId: rid ?? s.responseId,
          version: ver ?? s.version,
        }));

        const profileBlock = {
          id: "profile",
          name: "Personal Information & Subject",
          type: "profile",
          requireContactAtLeastOne: true,
        };

        if (cancelled) return;

        // Try restore from local meta (responseId/version)
        let restored = null;
        try {
          const rawMeta = localStorage.getItem(metaKey(srv.surveyId));
          if (rawMeta) restored = JSON.parse(rawMeta);
        } catch {}

        // Prefer responseId from server if it exists in envelope
        // (supports future backend addition like env.response.responseId or env.survey.responseId)
        const responseIdFromAccess =
          env?.response?.responseId ||
          env?.survey?.responseId ||
          null;

        setServer({
          surveyId: srv.surveyId,
          responseId: responseIdFromAccess ?? restored?.responseId ?? null,
          version: restored?.version ?? null,
        });

        // Build blocks (inject profile first)
        const srvBlocks = Array.isArray(srv.blocks) ? srv.blocks : [];
        const blocksWithProfile = [profileBlock, ...srvBlocks];

        // Prefill baseline + answers from server answerText (if any)
        const baseAnswers = {};
        for (const b of blocksWithProfile) {
          if (b.id === "profile") continue;
          if (Object.prototype.hasOwnProperty.call(b, "answerText") && b.answerText != null) {
            baseAnswers[b.id] = b.type === "rating" ? Number(b.answerText) : String(b.answerText);
          }
        }

        const hasServerAnswers = Object.keys(baseAnswers).length > 0;

        // Merge with any saved local answers (local wins only for in-progress)
        const savedLocal = (() => {
          try {
            return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
          } catch {
            return {};
          }
        })();

        const mergedAnswers = {
          ...baseAnswers,
          ...savedLocal,
          profile: { ...srv.respondent },
        };

        setBaseline(baseAnswers);
        setAnswers(mergedAnswers);

        setRuntime({
          deadlineISO: srv.deadlineISO,
          respondent: {
            firstName: srv.respondent.firstName,
            lastName: srv.respondent.lastName,
            email: srv.respondent.email || "",
            telegram: srv.respondent.telegram || "",
          },
          subject: {
            firstName: srv.subject.firstName,
            lastName: srv.subject.lastName,
          },
          blocks: blocksWithProfile,
        });

        const total = blocksWithProfile.length;

        // Respect server closure flag
        const isClosedServer = !!env?.isClosed;

        // If there were delivered answers → jump to final page
        if (hasServerAnswers || (restored?.responseId && allBlocksValid(blocksWithProfile, mergedAnswers))) {
          setVisited(Array(total).fill(true));
          setCurrent(total - 1);
          setSubmitted(true);
        } else {
          const startAt = computeStartIndex(blocksWithProfile, mergedAnswers);
          setVisited(Array.from({ length: total }, (_, i) => i <= startAt));
          setCurrent(startAt);
          setSubmitted(false);
        }

        setMeta((m) => ({
          ...m,
          hasServerAnswers,
          isClosedServer,
        }));
      } catch (e) {
        if (!cancelled) setMeta({ loading: false, error: e.message || String(e), hasServerAnswers: false, isClosedServer: false });
        return;
      } finally {
        if (!cancelled) setMeta((m) => ({ ...m, loading: false }));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [linkToken, apiBase]);

  /* ================
     Per-step helpers
  ================= */
  const block = runtime.blocks[current];
  const isCurrentValid = () => isBlockValidForAnswers(block, answers);

  function handleNext() {
    if (isClosed) return;
    const last = current === runtime.blocks.length - 1;
    if (last) {
      if (!isCurrentValid()) return;
      (async () => {
        try {
          await submitToAPI();
          setSubmitted(true);
        } catch (e) {
          alert(String(e));
        }
      })();
      return;
    }
    if (isCurrentValid()) setCurrent((i) => Math.min(runtime.blocks.length - 1, i + 1));
  }

  function jumpTo(index) {
    if (isClosed) return;
    if (visited[index]) setCurrent(index);
  }

  function setAnswer(id, value) {
    setAnswers((prev) => ({ ...prev, [id]: value }));
  }

  /* ================
     Submit helpers
  ================= */
  function buildAnsweredMap() {
    const out = {};
    for (const b of runtime.blocks) {
      if (b.type === "profile") continue;
      const v = answers[b.id];
      if (v === undefined) continue;
      out[b.id] = v;
    }
    return out;
  }

  function buildDeltaFromBaseline() {
    const full = buildAnsweredMap();
    // send only changed keys vs baseline
    const delta = {};
    for (const [k, v] of Object.entries(full)) {
      if (baseline[k] !== v) {
        delta[k] = v;
      }
    }
    return delta;
  }

  async function refetchAccessForResponseId() {
    const res = await fetch(`${apiBase}/v1/surveys/access/${linkToken}`);
    if (!res.ok) return null;
    const env = await res.json().catch(() => null);
    return (
      env?.response?.responseId ||
      env?.survey?.responseId ||
      null
    );
  }

  async function submitToAPI() {
    if (!server.surveyId || !linkToken) return;

    const client = {
      userAgent: (typeof navigator !== "undefined" && navigator.userAgent) || "",
      timezone: (Intl.DateTimeFormat().resolvedOptions()?.timeZone) || "",
      startedAtISO: startedAtRef.current?.toISOString(),
      submittedAtISO: new Date().toISOString(),
    };

    const headers = { "Content-Type": "application/json", "X-Survey-Token": linkToken };

    const answered = buildAnsweredMap();

    // NEW: if we have responseId → PATCH (editing flow)
    if (server.responseId) {
      const payload = { answersDelta: answered, client }; // delta or full map — backend accepts answersDelta
      const res = await fetch(
        `${apiBase}/v1/surveys/${server.surveyId}/responses/${server.responseId}`,
        { method: "PATCH", headers, body: JSON.stringify(payload) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`Update failed: ${res.status} ${res.statusText}${txt ? ` — ${txt}` : ""}`);
      }
      const data = await res.json(); // { version }
      setServer((s) => ({ ...s, version: data.version }));
      return;
    }

    // Otherwise → first-time submit via POST
    const payload = { answers: answered, client };
    const res = await fetch(
      `${apiBase}/v1/surveys/${server.surveyId}/responses`,
      { method: "POST", headers, body: JSON.stringify(payload) }
    );

    if (!res.ok) {
      // Optional safety net: if backend still races us with 409, refetch /access and retry once as PATCH
      if (res.status === 409) {
        const r = await fetch(`${apiBase}/v1/surveys/access/${linkToken}`).then(r => r.ok ? r.json() : null).catch(() => null);
        const rid2 = r?.response?.responseId ?? null;
        if (rid2) {
          setServer((s) => ({ ...s, responseId: rid2, version: r?.response?.version ?? s.version }));
          const patchPayload = { answersDelta: answered, client };
          const patch = await fetch(
            `${apiBase}/v1/surveys/${server.surveyId}/responses/${rid2}`,
            { method: "PATCH", headers, body: JSON.stringify(patchPayload) }
          );
          if (!patch.ok) {
            const txt = await patch.text().catch(() => "");
            throw new Error(`Update failed: ${patch.status} ${patch.statusText}${txt ? ` — ${txt}` : ""}`);
          }
          const data = await patch.json();
          setServer((s) => ({ ...s, version: data.version }));
          return;
        }
      }
    const txt = await res.text().catch(() => "");
    throw new Error(`Submit failed: ${res.status} ${res.statusText}${txt ? ` — ${txt}` : ""}`);
  }

  // POST success → remember responseId for future edits
  const data = await res.json(); // { responseId, version }
  setServer((s) => ({ ...s, responseId: data.responseId, version: data.version }));
  try {
    const mk = (sid) => (sid ? `surveyflow_meta_${sid}` : null);
    const key = mk(server.surveyId);
    if (key) localStorage.setItem(key, JSON.stringify({ responseId: data.responseId, version: data.version }));
  } catch {}
  }


  /* ================
     Progress
  ================= */
  const completedCount = useMemo(
    () => runtime.blocks.filter((b) => isBlockValidForAnswers(b, answers)).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [answers, runtime.blocks]
  );
  const progress = Math.round((completedCount / runtime.blocks.length) * 100);

  /* ================
     Guards
  ================= */
  if (!linkToken && !runtime?.blocks?.length) {
    return (
      <div className="min-h-screen w-full grid place-items-center">
        <div className="max-w-md w-full p-6 rounded-xl border border-white/20 bg-slate-900 text-white">
          <h2 className="text-xl font-semibold mb-3">Open a survey</h2>
          <p className="text-white/70 text-sm mb-4">
            Add <code>?token=...</code> to the URL, or run demo mode.
          </p>
          <div className="flex gap-2">
            <button
              className="px-4 py-2 rounded-lg bg-white text-slate-900"
              onClick={() => {
                setRuntime({
                  deadlineISO: demoDeadlineISO,
                  respondent: demoRespondent,
                  subject: demoSubject,
                  blocks: demoBlocks,
                });
              }}
            >
              Run demo
            </button>
            <button
              className="px-4 py-2 rounded-lg border border-white/30"
              onClick={() => {
                const t = prompt("Paste link token");
                if (t) window.location.search = `?token=${encodeURIComponent(t)}`;
              }}
            >
              Paste token…
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (meta.loading) {
    return (
      <div className="min-h-screen w-full grid place-items-center">
        <div className="text-white/70">Loading survey…</div>
      </div>
    );
  }

  if (meta.error) {
    return (
      <div className="min-h-screen w-full grid place-items-center">
        <div className="max-w-lg text-center text-red-200">
          Failed to load survey: {meta.error}
        </div>
      </div>
    );
  }

  /* ================
     Main UI
  ================= */
  return (
    <div className="min-h-screen w-full bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-3xl">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-4">
            {/* Title can shrink and ellipsize */}
            <h1 className="flex-1 min-w-0 truncate text-2xl md:text-3xl font-semibold tracking-tight text-white/90">
              {submitted ? "Review & Submit" : block?.name}
            </h1>

            {/* Right side never wraps / never shrinks */}
            <div className="flex items-center gap-3 shrink-0 whitespace-nowrap">

              <button
                onClick={resetAll}
                className="text-xs px-2 py-1 rounded-lg border border-white/25 text-white/80 hover:bg-white/10"
                title="Shift+R also resets"
              >
                Reset
              </button>

              {Number.isFinite(dLeft) && (
                <span
                  className={[
                    "inline-flex whitespace-nowrap text-xs px-2.5 py-1 rounded-full border",
                    isClosed ? "border-red-300 text-red-300" : "border-white/30 text-white/70",
                  ].join(" ")}
                  title={new Date(runtime.deadlineISO).toLocaleString()}
                >
                  {isClosed
                    ? "Closed"
                    : `${dLeft}\u00A0day${Math.abs(dLeft) === 1 ? "" : "s"}\u00A0left`}
                </span>
              )}

              <span className="text-sm text-white/60">
                {submitted
                  ? `${runtime.blocks.length}/${runtime.blocks.length}`
                  : `${current + 1}/${runtime.blocks.length}`}
              </span>
            </div>
          </div>
          {/* the rest stays the same */}


          <div className="mt-3 h-2 w-full bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-white/80 rounded-full transition-all duration-500"
              style={{ width: `${submitted ? 100 : progress}%` }}
            />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {runtime.blocks.map((b, idx) => {
              const isActive = !submitted && idx === current;
              const canClick = visited[idx] && !isClosed;
              const isDone = isBlockValidForAnswers(b, answers);
              return (
                <button
                  key={b.id}
                  onClick={() => canClick && jumpTo(idx)}
                  className={[
                    "px-3 py-1 rounded-full text-xs md:text-sm border",
                    isActive ? "bg-white text-slate-900 border-white" : "bg-white/5 text-white/80 border-white/20",
                    canClick ? "hover:bg-white/20" : "opacity-60 cursor-not-allowed",
                    isDone ? "ring-1 ring-white/60" : "",
                  ].join(" ")}
                  aria-label={`Go to step ${idx + 1}`}
                >
                  {idx + 1}
                </button>
              );
            })}
          </div>
        </header>

        <main className="relative">
          <div className="rounded-2xl bg-white/10 backdrop-blur p-6 md:p-10 shadow-xl ring-1 ring-white/10">
            {isClosed ? (
              <div className="text-center py-8">
                <div className="text-2xl font-semibold text-white/90 mb-2">This survey is closed</div>
                <div className="text-white/60">The deadline was {new Date(runtime.deadlineISO).toLocaleString()}.</div>
              </div>
            ) : (
              <AnimatePresence mode="wait" initial={false}>
                {submitted ? (
                  <motion.div
                    key="review"
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -12 }}
                    transition={{ duration: 0.25 }}
                    className="space-y-6"
                  >
                    <h2 className="text-xl font-medium text-white/90">Thanks! Here’s your submission:</h2>
                    <div className="space-y-4">
                      {runtime.blocks.map((b) => (
                        <div key={`rev-${b.id}`} className="rounded-xl border border-white/15 bg-white/5 p-4">
                          <div className="text-white/70 text-sm mb-1">
                            {b.name}
                            {b.optional ? " · Optional" : ""}
                          </div>
                          {b.type === "rating" && (
                            <div className="text-white text-lg">
                              {answers[b.id] ?? "— (skipped)"}
                            </div>
                          )}
                          {b.type === "text" && (
                            <p className="text-white/90 whitespace-pre-wrap">
                              {(answers[b.id] ?? "").trim() || "— (skipped)"}
                            </p>
                          )}
                          {b.type === "profile" &&
                            (() => {
                              const v = answers[b.id] || {};
                              return (
                                <div className="text-white/90 text-sm space-y-1">
                                  <div>
                                    <span className="text-white/60">You:</span> {v.firstName || "—"} {v.lastName || ""} ·{" "}
                                    {v.email || "—"} · {v.telegram ? `@${v.telegram}` : "—"}
                                  </div>
                                  <div>
                                    <span className="text-white/60">About:</span> {runtime.subject.firstName}{" "}
                                    {runtime.subject.lastName}
                                  </div>
                                </div>
                              );
                            })()}
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-3 pt-2">
                      <button
                        onClick={() => {
                          const i = computeStartIndex(runtime.blocks, answers);
                          setSubmitted(false);
                          setVisited(Array.from({ length: runtime.blocks.length }, (_, k) => k <= i));
                          setCurrent(i);
                        }}
                        className="px-4 py-2 rounded-xl bg-white text-slate-900 font-medium hover:opacity-90"
                      >
                        Edit Answers
                      </button>
                      <button
                        onClick={() => {
                          const blob = new Blob([JSON.stringify(answers, null, 2)], { type: "application/json" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = "survey_answers.json";
                          a.click();
                          URL.revokeObjectURL(url);
                        }}
                        className="px-4 py-2 rounded-xl bg-white/10 text-white font-medium border border-white/20 hover:bg-white/15"
                      >
                        Download JSON
                      </button>
                      <button
                        onClick={resetAll}
                        className="px-4 py-2 rounded-xl bg-white/10 text-white font-medium border border-white/20 hover:bg-white/15"
                        title="Clear local data and restart"
                      >
                        Reset All
                      </button>
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key={block?.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -16 }}
                    transition={{ duration: 0.25 }}
                    className="space-y-8"
                  >
                    {block?.type === "profile" && (
                      <ProfileStep value={answers[block.id]} subject={runtime.subject} />
                    )}

                    {block?.type === "rating" && (
                      <RatingStep
                        question={block.question}
                        min={block.min ?? 1}
                        max={block.max ?? 10}
                        value={answers[block.id]}
                        onChange={(v) => setAnswer(block.id, v)}
                        onAnswered={() => setTimeout(() => handleNext(), 0)}
                        optional={block.optional}
                      />
                    )}

                    {block?.type === "text" && (
                      <TextStep
                        prompt={block.prompt}
                        placeholder={block.placeholder}
                        minLength={block.minLength}
                        value={answers[block.id] || ""}
                        onChange={(v) => setAnswer(block.id, v)}
                        optional={block.optional}
                      />
                    )}

                    <NavBar
                      disableBack={current === 0}
                      disableNext={!isCurrentValid()}
                      isLast={current === runtime.blocks.length - 1}
                      onBack={() => setCurrent((i) => Math.max(0, i - 1))}
                      onNext={handleNext}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            )}
          </div>
        </main>

        <footer className="mt-6 text-center text-xs text-white/40">
          Сделано командой xUI — Студия Артемия Лебедева.
        </footer>
      </div>
    </div>
  );
}

/* =========================
   Small components
========================= */
function OptionalBadge() {
  return (
    <span className="ml-2 align-middle text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border border-white/25 text-white/60">
      Optional
    </span>
  );
}

function NavBar({ disableBack, disableNext, isLast, onBack, onNext }) {
  return (
    <div className="flex items-center justify-between pt-2">
      <button
        onClick={onBack}
        disabled={disableBack}
        className={[
          "px-4 py-2 rounded-xl border text-white/90",
          disableBack ? "border-white/15 bg-white/5 opacity-50 cursor-not-allowed" : "border-white/25 bg-white/10 hover:bg-white/15",
        ].join(" ")}
      >
        ← Back
      </button>
      <button
        onClick={onNext}
        disabled={disableNext}
        className={[
          "px-5 py-2 rounded-xl font-medium",
          disableNext ? "bg-white/30 cursor-not-allowed text-slate-900/60" : "bg-white text-slate-900 hover:opacity-90",
        ].join(" ")}
      >
        {isLast ? "Submit" : "Next →"}
      </button>
    </div>
  );
}

function ProfileStep({ value, subject }) {
  const v = value || { firstName: "", lastName: "", email: "", telegram: "" };
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-white/20 bg-white/5 p-4">
          <div className="text-sm text-white/60 mb-1">You</div>
          <div className="text-white/90 text-lg font-medium">
            {v.firstName} {v.lastName}
          </div>
          <div className="text-white/70 text-sm mt-1">Email: {v.email || "—"}</div>
          <div className="text-white/70 text-sm">Telegram: {v.telegram ? `@${v.telegram}` : "—"}</div>
        </div>
        <div className="rounded-xl border border-white/20 bg-white/5 p-4">
          <div className="text-sm text-white/60 mb-1">About (subject)</div>
          <div className="text-white/90 text-lg font-medium">
            {subject?.firstName} {subject?.lastName}
          </div>
          <div className="text-white/60 text-xs mt-1">
            This survey is about this person. Please rate and comment accordingly.
          </div>
        </div>
      </div>
      <div className="text-xs text-white/50">
        Your personal data is prefilled and cannot be edited in this survey link.
      </div>
    </div>
  );
}

function RatingStep({ question, min = 1, max = 10, value, onChange, onAnswered, optional = false }) {
  const scale = Array.from({ length: max - min + 1 }, (_, i) => i + min);
  return (
    <div>
      <h2 className="text-lg md:text-xl font-medium text-white/90 mb-4">
        {question}
        {optional && <OptionalBadge />}
      </h2>
      <div className="flex items-center gap-3 flex-wrap">
        {scale.map((n) => {
          const active = value === n;
          return (
            <button
              key={n}
              onClick={() => {
                onChange(n);
                if (typeof onAnswered === "function") onAnswered();
              }}
              aria-label={`Rate ${n}`}
              className={[
                "h-10 w-10 rounded-full grid place-items-center border transition",
                active ? "bg-white text-slate-900 border-white shadow" : "bg-white/5 text-white/80 border-white/20 hover:bg-white/15",
              ].join(" ")}
            >
              {n}
            </button>
          );
        })}
        {optional && (value === undefined || value === null) && (
          <span className="text-xs text-white/50">(You may skip this)</span>
        )}
      </div>
      <div className="mt-3 text-xs text-white/50">1 = Low, 10 = High</div>
    </div>
  );
}

function TextStep({ prompt, placeholder = "", minLength = 0, value, onChange, optional = false }) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  const empty = (value ?? "").trim().length === 0;
  return (
    <div>
      <h2 className="text-lg md:text-xl font-medium text-white/90 mb-3">
        {prompt}
        {optional && <OptionalBadge />}
      </h2>
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={6}
        className="w-full rounded-xl bg-white/5 border border-white/20 text-white placeholder-white/40 p-4 focus:outline-none focus:ring-2 focus:ring-white/40"
      />
      {optional && empty && <div className="mt-2 text-xs text-white/50">(You may leave this empty)</div>}
      {!optional && minLength > 0 && (
        <div className="mt-2 text-xs text-white/50">Minimum {minLength} character(s).</div>
      )}
    </div>
  );
}

/* =========================
   Mini runtime tests
========================= */
if (typeof window !== "undefined" && !window.__SURVEYFLOW_TESTS_RAN__) {
  try {
    console.assert(typeof API_BASE === "string" && API_BASE.length > 0, "API_BASE resolved");

    const answers = {};
    const rb = { id: "r1", name: "R", type: "rating", question: "q", min: 1, max: 10 };
    console.assert(isBlockValidForAnswers(rb, answers) === false, "rating: empty invalid");
    answers["r1"] = 7;
    console.assert(isBlockValidForAnswers(rb, answers) === true, "rating: 7 valid");
    answers["r1"] = 0;
    console.assert(isBlockValidForAnswers(rb, answers) === false, "rating: 0 invalid");

    const tb = { id: "t1", name: "T", type: "text", prompt: "p", minLength: 2 };
    console.assert(isBlockValidForAnswers(tb, answers) === false, "text: empty invalid when minLength=2");
    answers["t1"] = "ok";
    console.assert(isBlockValidForAnswers(tb, answers) === true, "text: len2 valid");

    const pb = { id: "p1", name: "P", type: "profile" };
    answers["p1"] = { firstName: "A", lastName: "B", email: "a@b.co", telegram: "" };
    console.assert(isBlockValidForAnswers(pb, answers) === true, "profile: names+email valid");

    const inTwoDays = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString();
    const inMinusOne = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    console.assert(daysLeft(inTwoDays) >= 1, "daysLeft ~>=1");
    console.assert(daysLeft(inMinusOne) <= 0, "daysLeft negative when past");
  } catch (e) {
    // swallow in prod
  } finally {
    window.__SURVEYFLOW_TESTS_RAN__ = true;
  }
}
