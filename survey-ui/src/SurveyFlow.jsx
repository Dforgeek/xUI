import React, { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
// === API config ===
const API_BASE =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) ||
  process.env.REACT_APP_API_BASE ||
  "http://localhost:8000"; // adjust if different

// Read link token from URL (?token=...)
function readLinkTokenFromURL() {
  try {
    const sp = new URLSearchParams(window.location.search);
    return sp.get("token") || sp.get("t") || null;
  } catch { return null; }
}

/**
 * SurveyFlow — Single‑block‑per‑page survey UI
 * -------------------------------------------------
 * Features
 * - One survey block per page, block name on top
 * - Supports rating (1–10 dots) and open comment questions
 * - Optional questions supported (flag per block) with clear UI indication and validation rules
 * - First page shows personal info (read‑only, prefilled via props); subject (the person being reviewed) is displayed alongside
 * - Deadline badge (right‑top). After deadline passes the form is closed
 * - Back to old blocks; forward only after completing current
 * - Clickable progress chips for visited blocks (back or forward to any visited step)
 * - Smooth page transitions (Framer Motion)
 * - Keyboard: ←/→ to navigate; Enter for Next/Submit when valid; Shift+R to reset
 * - LocalStorage persistence
 * - Clean, modern UI with Tailwind
 *
 * Usage:
 *   <SurveyFlow
 *      blocks={yourBlocks}
 *      deadlineISO="2025-12-31T23:59:59Z"
 *      respondent={{ firstName: 'Jane', lastName: 'Doe', email: 'jane@acme.com', telegram: 'jane_d' }}
 *      subject={{ firstName: 'John', lastName: 'Smith' }}
 *   />
 */

/**
 * Block typedefs (JSDoc for intellisense)
 * @typedef {Object} RatingBlock
 * @property {string} id
 * @property {string} name      // block name shown on top
 * @property {"rating"} type
 * @property {string} question
 * @property {number} [min]
 * @property {number} [max]
 * @property {boolean} [optional] // if true, question may be skipped
 *
 * @typedef {Object} TextBlock
 * @property {string} id
 * @property {string} name      // block name shown on top
 * @property {"text"} type
 * @property {string} prompt
 * @property {string} [placeholder]
 * @property {number} [minLength]
 * @property {boolean} [optional] // if true, may be left empty
 *
 * @typedef {Object} ProfileBlock
 * @property {string} id
 * @property {string} name      // block name shown on top
 * @property {"profile"} type
 * @property {boolean} [requireContactAtLeastOne] // if true, require email or telegram
 *
 * @typedef {RatingBlock|TextBlock|ProfileBlock} Block
 */

// ---------------------------
// Demo schema & demo props
// ---------------------------
const demoBlocks = /** @type {Block[]} */ ([
  { id: "profile", name: "Personal Information & Subject", type: "profile", requireContactAtLeastOne: true },
  { id: "b1", name: "Ваша удовлетворённость этим фронтендом", type: "rating", question: "Как оцениваете?", min: 1, max: 10 },
  { id: "b2", name: "Тон цвета (опционально)", type: "rating", question: "Тон цвета оцените от 1 до 10", min: 1, max: 10, optional: true },
  { id: "b3", name: "Если есть что добавить (опционально)", type: "text", prompt: "Расскажите что угодно, чем ещё хочется поделиться", placeholder: "Писать здесь...", minLength: 1, optional: true },
]);

const demoRespondent = { firstName: "Jane", lastName: "Doe", email: "jane@example.com", telegram: "jane_d" };
const demoSubject    = { firstName: "John", lastName: "Smith" };
const demoDeadlineISO = "2099-12-31T23:59:59Z"; // far future for demo

const LS_KEY = "surveyflow_answers_v1";

// ---------------------------
// Helpers (pure)
// ---------------------------
function isEmailValid(email) {
  if (!email) return false;
  return /.+@.+\..+/.test(email);
}

/** Days left until deadline. Returns integer days (ceil), can be negative when past */
function daysLeft(deadlineISO) {
  if (!deadlineISO) return Infinity;
  const now = Date.now();
  const end = Date.parse(deadlineISO);
  if (Number.isNaN(end)) return Infinity;
  const ms = end - now;
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

/**
 * @param {Block} b
 * @param {Record<string, any>} answers
 */
function isBlockValidForAnswers(b, answers) {
  if (!b) return false;
  if (b.type === "rating") {
    const v = answers[b.id];
    // Optional rating: valid when unanswered
    if (b.optional && (v === undefined || v === null)) return true;
    return typeof v === "number" && v >= (b.min ?? 1) && v <= (b.max ?? 10);
  }
  if (b.type === "text") {
    const tRaw = answers[b.id] ?? "";
    const t = String(tRaw).trim();
    // Optional text: valid when empty
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
  linkToken: linkTokenProp = null,           // allow explicit prop, or URL param
}) {
  const linkToken = linkTokenProp ?? readLinkTokenFromURL();
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState(() => {
    const raw = typeof window !== "undefined" ? localStorage.getItem(LS_KEY) : null;
    return raw ? JSON.parse(raw) : {};
  });
  const [visited, setVisited] = useState(() => Array(blocksProp.length).fill(false));
  const [submitted, setSubmitted] = useState(false);
  const [server, setServer] = useState({ surveyId: null, responseId: null, version: null });
  const [meta, setMeta] = useState({ loading: !!linkToken, error: null });
  const [runtime, setRuntime] = useState({
    deadlineISO: deadlineISOProp,
    respondent: respondentProp,
    subject: subjectProp,
    blocks: blocksProp,
  });
  const startedAtRef = useRef(new Date()); // for client meta

  // Reset all local state and localStorage (re‑prefill profile)
  function resetAll() {
    try { if (typeof window !== 'undefined') localStorage.removeItem(LS_KEY); } catch {}
    const prof = runtime.blocks.find((b) => b.type === "profile");
    const base = prof ? { [prof.id]: { ...runtime.respondent } } : {};
    setAnswers(base);
    setVisited(Array.from({ length: runtime.blocks.length }, (_, i) => i === 0));
    setSubmitted(false);
    setCurrent(0);
  }

  const dLeft = daysLeft(runtime.deadlineISO);
  const isClosed = Number.isFinite(dLeft) && dLeft <= 0;

  // Pre-fill profile answers once (read-only profile)
  useEffect(() => {
    const prof = runtime.blocks.find((b) => b.type === "profile");
    if (prof && !answers[prof.id]) {
      setAnswers((prev) => ({ ...prev, [prof.id]: { ...runtime.respondent } }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist answers
  useEffect(() => {
    localStorage.setItem(LS_KEY, JSON.stringify(answers));
  }, [answers]);

  // Mark visited on enter
  useEffect(() => {
    setVisited((prev) => {
      const next = [...prev];
      next[current] = true;
      return next;
    });
  }, [current]);

  // Keyboard navigation (disabled when closed)
  useEffect(() => {
    if (isClosed) return;
    const onKey = (e) => {
      if (e.key === "ArrowLeft") {
        handleBack();
      } else if (e.key === "ArrowRight") {
        handleNext();
      } else if (e.key === "Enter") {
        if (isCurrentValid()) handleNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Keyboard shortcut: Shift+R to reset answers
  useEffect(() => {
    const onKey = (e) => {
      if ((e.key === 'R' || e.key === 'r') && e.shiftKey) {
        e.preventDefault();
        resetAll();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // URL param ?reset=1 to clear storage on load
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      if (sp.get('reset') === '1') {
        resetAll();
      }
    } catch {}
  }, []);
  // Load envelope when we have a linkToken; otherwise stay in demo mode
  useEffect(() => {
    if (!linkToken) return;
    let cancelled = false;

    (async () => {
      try {
        setMeta((m) => ({ ...m, loading: true, error: null }));
        const res = await fetch(`${apiBase}/v1/surveys/access/${linkToken}`);
        if (!res.ok) {
          // 410 = closed; 401 = bad token; bubble others
          const text = await res.text().catch(() => "");
          throw new Error(`${res.status} ${res.statusText}${text ? ` — ${text}` : ""}`);
        }
        const env = await res.json();
        const srv = env.survey;

        // Prepend a synthetic 'profile' block for your UI (backend only sends q* blocks)
        const profileBlock = {
          id: "profile",
          name: "Personal Information & Subject",
          type: "profile",
          requireContactAtLeastOne: true,
        };

        if (!cancelled) {
          setServer({ surveyId: srv.surveyId, responseId: null, version: null });
          setRuntime({
            deadlineISO: srv.deadlineISO,
            respondent: {
              firstName: srv.respondent.firstName,
              lastName:  srv.respondent.lastName,
              email:     srv.respondent.email || "",
              telegram:  srv.respondent.telegram || "",
            },
            subject: {
              firstName: srv.subject.firstName,
              lastName:  srv.subject.lastName,
            },
            blocks: [profileBlock, ...(srv.blocks || [])],
          });
          // Re-prefill profile with respondent from server
          const saved = (() => {
            try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch { return {}; }
          })();
          const mergedAnswers = { ...saved, profile: { ...srv.respondent } };
          setAnswers(mergedAnswers);
          
          const total = (srv.blocks?.length ?? 0) + 1; // +1 for profile
          const startAt = computeStartIndex([profileBlock, ...(srv.blocks || [])], mergedAnswers);
          setVisited(Array.from({ length: total }, (_, i) => i <= startAt));
          setCurrent(startAt);
          setSubmitted(false);
        }
      } catch (e) {
        if (!cancelled) setMeta({ loading: false, error: e.message || String(e) });
        return;
      } finally {
        if (!cancelled) setMeta((m) => ({ ...m, loading: false }));
      }
    })();

    return () => { cancelled = true; };
  }, [linkToken, apiBase]);

  const block = runtime.blocks[current];

  const isCurrentValid = () => isBlockValidForAnswers(block, answers);

  function handleBack() {
    if (isClosed) return;
    setCurrent((i) => Math.max(0, i - 1));
  }

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
            alert(String(e)); // replace with your toast
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
  

  // APIIIIIII
    function buildAnsweredMap() {
    // Only send answerable blocks (skip 'profile'); omit truly empty/undefined
    const out = {};
    for (const b of runtime.blocks) {
      if (b.type === "profile") continue;
      const v = answers[b.id];
      if (v === undefined) continue;     // omit unanswered
      out[b.id] = v;
    }
    return out;
  }
  function computeStartIndex(blocks, answers) {
  // first block that is NOT valid → we start there; if all valid → last block
  for (let i = 0; i < blocks.length; i++) {
    if (!isBlockValidForAnswers(blocks[i], answers)) return i;
  }
  return Math.max(0, blocks.length - 1);
}


  async function submitToAPI() {
    if (!server.surveyId || !linkToken) return;

    const client = {
      userAgent: (typeof navigator !== "undefined" && navigator.userAgent) || "",
      timezone:  (Intl.DateTimeFormat().resolvedOptions()?.timeZone) || "",
      startedAtISO: startedAtRef.current?.toISOString(),
      submittedAtISO: new Date().toISOString(),
    };

    const headers = { "Content-Type": "application/json", "X-Survey-Token": linkToken };

    if (!server.responseId) {
      // First submission → POST
      const payload = { answers: buildAnsweredMap(), client };
      const res = await fetch(`${apiBase}/v1/surveys/${server.surveyId}/responses`, {
        method: "POST", headers, body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`Submit failed: ${res.status} ${res.statusText}${txt ? ` — ${txt}` : ""}`);
      }
      const data = await res.json(); // { responseId, version, ... }
      setServer((s) => ({ ...s, responseId: data.responseId, version: data.version }));
    } else {
      // Subsequent edits → PATCH (only deltas, but here we can just resend map as delta)
      const payload = { answersDelta: buildAnsweredMap(), client };
      const res = await fetch(`${apiBase}/v1/surveys/${server.surveyId}/responses/${server.responseId}`, {
        method: "PATCH", headers, body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`Update failed: ${res.status} ${res.statusText}${txt ? ` — ${txt}` : ""}`);
      }
      const data = await res.json(); // { version, ... }
      setServer((s) => ({ ...s, version: data.version }));
    }
  }





  // Completion ratio for progress bar
  const completedCount = useMemo(
    () => runtime.blocks.filter((b) => isBlockValidForAnswers(b, answers)).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [answers, runtime.blocks]
  );
  const progress = Math.round((completedCount / runtime.blocks.length) * 100);



  if (!linkToken && !runtime?.blocks?.length) {
  // No token AND no demo blocks → show picker
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
              // force demo state
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
  return (
    
    <div className="min-h-screen w-full bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-3xl">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-4">
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-white/90">
              {submitted ? "Review & Submit" : block?.name}
            </h1>
            <div className="flex items-center gap-3">
              {/* Reset button */}
              <button
                onClick={resetAll}
                className="text-xs px-2 py-1 rounded-lg border border-white/25 text-white/80 hover:bg-white/10"
                title="Shift+R also resets"
                disabled={false}
              >
                Reset
              </button>
              {/* Deadline badge */}
              {Number.isFinite(dLeft) && (
                <span className={[
                  "text-xs px-2.5 py-1 rounded-full border",
                  isClosed ? "border-red-300 text-red-300" : "border-white/30 text-white/70",
                ].join(" ")}
                title={new Date(runtime.deadlineISO).toLocaleString()}>
                  {isClosed ? "Closed" : `${dLeft} day${Math.abs(dLeft) === 1 ? "" : "s"} left`}
                </span>
              )}
              <span className="text-sm text-white/60">{submitted ? `${runtime.blocks.length}/${runtime.blocks.length}` : `${current + 1}/${runtime.blocks.length}`}</span>
            </div>
          </div>

          {/* Progress bar */}
          <div className="mt-3 h-2 w-full bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-white/80 rounded-full transition-all duration-500"
              style={{ width: `${submitted ? 100 : progress}%` }}
            />
          </div>

          {/* Step chips */}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {runtime.blocks.map((b, idx) => {
              const isActive = !submitted && idx === current;
              const canClick = visited[idx] && !isClosed; // allow jump to any visited step
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
                          <div className="text-white/70 text-sm mb-1">{b.name}{b.optional ? ' · Optional' : ''}</div>
                          {b.type === "rating" && (
                            <div className="text-white text-lg">{answers[b.id] ?? '— (skipped)'}</div>
                          )}
                          {b.type === "text" && (
                            <p className="text-white/90 whitespace-pre-wrap">{(answers[b.id] ?? '').trim() || '— (skipped)'}</p>
                          )}
                          {b.type === "profile" && (
                            (() => {
                              const v = answers[b.id] || {};
                              return (
                                <div className="text-white/90 text-sm space-y-1">
                                  <div><span className="text-white/60">You:</span> {v.firstName || "—"} {v.lastName || ""} · {v.email || "—"} · {v.telegram ? `@${v.telegram}` : "—"}</div>
                                  <div><span className="text-white/60">About:</span> {runtime.subject.firstName} {runtime.subject.lastName}</div>
                                </div>
                              );
                            })()
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-3 pt-2">
                      <button
                        onClick={() => {
                          setSubmitted(false);
                          setCurrent(0);
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
                      <ProfileStep
                        value={answers[block.id]}
                        subject={runtime.subject}
                      />
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
                      onBack={handleBack}
                      onNext={handleNext}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            )}
          </div>
        </main>

        <footer className="mt-6 text-center text-xs text-white/40">
          Сделано командоЙ xUI -- Студия Артемия Лебедева.
        </footer>
      </div>
    </div>
  );
}

function OptionalBadge() {
  return (
    <span className="ml-2 align-middle text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border border-white/25 text-white/60">Optional</span>
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
          disableBack
            ? "border-white/15 bg-white/5 opacity-50 cursor-not-allowed"
            : "border-white/25 bg-white/10 hover:bg-white/15",
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
  // Read‑only display of respondent + subject
  const v = value || { firstName: "", lastName: "", email: "", telegram: "" };
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-white/20 bg-white/5 p-4">
          <div className="text-sm text-white/60 mb-1">You</div>
          <div className="text-white/90 text-lg font-medium">{v.firstName} {v.lastName}</div>
          <div className="text-white/70 text-sm mt-1">Email: {v.email || "—"}</div>
          <div className="text-white/70 text-sm">Telegram: {v.telegram ? `@${v.telegram}` : "—"}</div>
        </div>
        <div className="rounded-xl border border-white/20 bg-white/5 p-4">
          <div className="text-sm text-white/60 mb-1">About (subject)</div>
          <div className="text-white/90 text-lg font-medium">{subject?.firstName} {subject?.lastName}</div>
          <div className="text-white/60 text-xs mt-1">This survey is about this person. Please rate and comment accordingly.</div>
        </div>
      </div>
      <div className="text-xs text-white/50">Your personal data is prefilled and cannot be edited in this survey link.</div>
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
              onClick={() => { onChange(n); if (typeof onAnswered === 'function') onAnswered(); }}
              aria-label={`Rate ${n}`}
              className={[
                "h-10 w-10 rounded-full grid place-items-center border transition",
                active
                  ? "bg-white text-slate-900 border-white shadow"
                  : "bg-white/5 text-white/80 border-white/20 hover:bg-white/15",
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
    // auto-focus when step mounts
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
      {optional && empty && (
        <div className="mt-2 text-xs text-white/50">(You may leave this empty)</div>
      )}
      {!optional && minLength > 0 && (
        <div className="mt-2 text-xs text-white/50">Minimum {minLength} character(s).</div>
      )}
    </div>
  );
}

// ---------------------------
// Basic runtime tests (dev only)
// ---------------------------
if (typeof window !== 'undefined' && !window.__SURVEYFLOW_TESTS_RAN__) {
  try {
    const answers = {};
    // rating (required)
    const rb = { id: 'r1', name: 'R', type: 'rating', question: 'q', min: 1, max: 10 };
    console.assert(isBlockValidForAnswers(rb, answers) === false, 'rating: empty should be invalid');
    answers['r1'] = 7;
    console.assert(isBlockValidForAnswers(rb, answers) === true, 'rating: 7 within 1..10 valid');
    answers['r1'] = 0;
    console.assert(isBlockValidForAnswers(rb, answers) === false, 'rating: 0 invalid');

    // text (required)
    const tb = { id: 't1', name: 'T', type: 'text', prompt: 'p', minLength: 2 };
    console.assert(isBlockValidForAnswers(tb, answers) === false, 'text: empty invalid when minLength=2');
    answers['t1'] = 'ok';
    console.assert(isBlockValidForAnswers(tb, answers) === true, 'text: length 2 valid');

    // profile (prefilled)
    const pb = { id: 'p1', name: 'P', type: 'profile' };
    answers['p1'] = { firstName: 'A', lastName: 'B', email: 'a@b.co', telegram: '' };
    console.assert(isBlockValidForAnswers(pb, answers) === true, 'profile: names + email valid');

    // daysLeft helper
    const inTwoDays = new Date(Date.now() + 2*24*60*60*1000).toISOString();
    const inMinusOne = new Date(Date.now() - 24*60*60*1000).toISOString();
    console.assert(daysLeft(inTwoDays) >= 1, 'daysLeft ~>=1');
    console.assert(daysLeft(inMinusOne) <= 0, 'daysLeft negative when past');

    // email validator
    console.assert(isEmailValid('') === false, 'email: empty invalid');
    console.assert(isEmailValid('x@y.z') === true, 'email: simple valid');

    // OPTIONAL RATING
    const or = { id: 'or1', name: 'OR', type: 'rating', question: 'q', min: 1, max: 10, optional: true };
    console.assert(isBlockValidForAnswers(or, {}) === true, 'optional rating: unanswered should be valid');
    const ans2 = { or1: 11 };
    console.assert(isBlockValidForAnswers(or, ans2) === false, 'optional rating: out of range invalid when answered');

    // OPTIONAL TEXT
    const ot = { id: 'ot1', name: 'OT', type: 'text', prompt: 'p', minLength: 5, optional: true };
    console.assert(isBlockValidForAnswers(ot, {}) === true, 'optional text: empty valid');
    const ans3 = { ot1: 'abcd' };
    console.assert(isBlockValidForAnswers(ot, ans3) === false, 'optional text: too short invalid when answered');
    const ans4 = { ot1: 'abcde' };
    console.assert(isBlockValidForAnswers(ot, ans4) === true, 'optional text: meets min when answered');
  } catch (e) {
    // swallow in production
  } finally {
    window.__SURVEYFLOW_TESTS_RAN__ = true;
  }
}
