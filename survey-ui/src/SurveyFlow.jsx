import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

/**
 * SurveyFlow — Single‑block‑per‑page survey UI
 * Features
 * - One survey block per page, block name on top
 * - Supports rating (1–10 dots) and open comment questions
 * - First page collects personal info (name, surname, email, telegram) with a "Stay Anonymous" toggle
 * - Back to old blocks; forward only after completing current
 * - Clickable progress chips for visited blocks (back or forward to any visited step)
 * - Smooth page transitions (Framer Motion)
 * - Keyboard: ←/→ to navigate; Enter for Next/Submit when valid
 * - LocalStorage persistence
 * - Clean, modern UI with Tailwind
 */

// Demo schema
const demoBlocks = [
  {
    id: 'profile',
    name: 'Personal Information',
    type: 'profile',
    requireContactAtLeastOne: true,
  },
  {
    id: 'b1',
    name: 'Ваша удовлетворённость этим фронтендом',
    type: 'rating',
    question: 'Как оцениваете?',
    min: 1,
    max: 10,
  },
  {
    id: 'b2',
    name: 'Тон цвета',
    type: 'rating',
    question: 'Тон цвета оцените от 1 до 10',
    min: 1,
    max: 10,
  },
  {
    id: 'b3',
    name: 'Если есть что добавить',
    type: 'text',
    prompt: 'Расскажите что угодно, чем ещё хочется поделиться',
    placeholder: 'Писать здесь...',
    minLength: 1,
  },
]

const LS_KEY = 'surveyflow_answers_v1'

// Validation helpers
function isEmailValid(email) {
  if (!email) return false
  return /.+@.+\..+/.test(email)
}

function isBlockValidForAnswers(b, answers) {
  if (!b) return false
  if (b.type === 'rating') {
    const v = answers[b.id]
    return typeof v === 'number' && v >= (b.min ?? 1) && v <= (b.max ?? 10)
  }
  if (b.type === 'text') {
    const t = (answers[b.id] || '').trim()
    const min = b.minLength ?? 0
    return t.length >= min
  }
  if (b.type === 'profile') {
    const v = answers[b.id] || {}
    if (v.anonymous) return true
    const first = (v.firstName || '').trim()
    const last = (v.lastName || '').trim()
    const email = (v.email || '').trim()
    const tg = (v.telegram || '').trim()
    const hasNames = first.length > 0 && last.length > 0
    const hasContact = b.requireContactAtLeastOne ? (isEmailValid(email) || tg.length > 0) : true
    return hasNames && hasContact
  }
  return false
}

export default function SurveyFlow({ blocks = demoBlocks }) {
  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState(() => {
    const raw = typeof window !== 'undefined' ? localStorage.getItem(LS_KEY) : null
    return raw ? JSON.parse(raw) : {}
  })
  const [visited, setVisited] = useState(() => Array(blocks.length).fill(false))
  const [submitted, setSubmitted] = useState(false)

  // Persist answers
  useEffect(() => {
    localStorage.setItem(LS_KEY, JSON.stringify(answers))
  }, [answers])

  // Mark visited on enter
  useEffect(() => {
    setVisited((prev) => {
      const next = [...prev]
      next[current] = true
      return next
    })
  }, [current])

  // Keyboard navigation
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowLeft') {
        handleBack()
      } else if (e.key === 'ArrowRight') {
        handleNext()
      } else if (e.key === 'Enter') {
        if (isCurrentValid()) handleNext()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const block = blocks[current]

  const isCurrentValid = () => isBlockValidForAnswers(block, answers)

  function handleBack() {
    setCurrent((i) => Math.max(0, i - 1))
  }

  function handleNext() {
    if (current === blocks.length - 1) {
      if (isCurrentValid()) setSubmitted(true)
      return
    }
    if (isCurrentValid()) setCurrent((i) => Math.min(blocks.length - 1, i + 1))
  }

  function jumpTo(index) {
    if (visited[index]) setCurrent(index) // allow jump to any visited step
  }

  function setAnswer(id, value) {
    setAnswers((prev) => ({ ...prev, [id]: value }))
  }

  const completedCount = useMemo(
    () => blocks.filter((b) => isBlockValidForAnswers(b, answers)).length,
    [answers, blocks]
  )
  const progress = Math.round((completedCount / blocks.length) * 100)

  return (
    <div className="min-h-screen w-full bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-3xl">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-4">
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-white/90">
              {submitted ? 'Review & Submit' : block?.name}
            </h1>
            <span className="text-sm text-white/60">{submitted ? `${blocks.length}/${blocks.length}` : `${current + 1}/${blocks.length}`}</span>
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
            {blocks.map((b, idx) => {
              const isActive = !submitted && idx === current
              const canClick = visited[idx]
              const isDone = isBlockValidForAnswers(b, answers)
              return (
                <button
                  key={b.id}
                  onClick={() => canClick && jumpTo(idx)}
                  className={[
                    'px-3 py-1 rounded-full text-xs md:text-sm border',
                    isActive ? 'bg-white text-slate-900 border-white' : 'bg-white/5 text-white/80 border-white/20',
                    canClick ? 'hover:bg-white/20' : 'opacity-60 cursor-not-allowed',
                    isDone ? 'ring-1 ring-white/60' : '',
                  ].join(' ')}
                  aria-label={`Go to step ${idx + 1}`}
                >
                  {idx + 1}
                </button>
              )
            })}
          </div>
        </header>

        <main className="relative">
          <div className="rounded-2xl bg-white/10 backdrop-blur p-6 md:p-10 shadow-xl ring-1 ring-white/10">
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
                    {blocks.map((b) => (
                      <div key={`rev-${b.id}`} className="rounded-xl border border-white/15 bg-white/5 p-4">
                        <div className="text-white/70 text-sm mb-1">{b.name}</div>
                        {b.type === 'rating' && (
                          <div className="text-white text-lg">{answers[b.id]}</div>
                        )}
                        {b.type === 'text' && (
                          <p className="text-white/90 whitespace-pre-wrap">{answers[b.id] || '—'}</p>
                        )}
                        {b.type === 'profile' && (
                          (() => {
                            const v = answers[b.id] || {}
                            if (v.anonymous) return <div className="text-white">Anonymous</div>
                            return (
                              <div className="text-white/90 text-sm space-y-1">
                                <div><span className="text-white/60">Name:</span> {v.firstName || '—'} {v.lastName || ''}</div>
                                <div><span className="text-white/60">Email:</span> {v.email || '—'}</div>
                                <div><span className="text-white/60">Telegram:</span> {v.telegram || '—'}</div>
                              </div>
                            )
                          })()
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 pt-2">
                    <button
                      onClick={() => { setSubmitted(false); setCurrent(0); }}
                      className="px-4 py-2 rounded-xl bg-white text-slate-900 font-medium hover:opacity-90"
                    >
                      Edit Answers
                    </button>
                    <button
                      onClick={() => {
                        const blob = new Blob([JSON.stringify(answers, null, 2)], { type: 'application/json' })
                        const url = URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = 'survey_answers.json'
                        a.click()
                        URL.revokeObjectURL(url)
                      }}
                      className="px-4 py-2 rounded-xl bg-white/10 text-white font-medium border border-white/20 hover:bg-white/15"
                    >
                      Download JSON
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
                  {block?.type === 'profile' && (
                    <ProfileStep
                      value={answers[block.id]}
                      onChange={(v) => setAnswer(block.id, v)}
                      requireContactAtLeastOne={block.requireContactAtLeastOne}
                    />
                  )}

                  {block?.type === 'rating' && (
                    <RatingStep
                      question={block.question}
                      min={block.min ?? 1}
                      max={block.max ?? 10}
                      value={answers[block.id]}
                      onChange={(v) => setAnswer(block.id, v)}
                      onAnswered={() => setTimeout(() => handleNext(), 0)}
                    />
                  )}

                  {block?.type === 'text' && (
                    <TextStep
                      prompt={block.prompt}
                      placeholder={block.placeholder}
                      minLength={block.minLength}
                      value={answers[block.id] || ''}
                      onChange={(v) => setAnswer(block.id, v)}
                    />
                  )}

                  <NavBar
                    disableBack={current === 0}
                    disableNext={!isCurrentValid()}
                    isLast={current === blocks.length - 1}
                    onBack={handleBack}
                    onNext={handleNext}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </main>

        <footer className="mt-6 text-center text-xs text-white/40">
          Built with ♥ for one‑block‑per‑page surveys.
        </footer>
      </div>
    </div>
  )
}

function NavBar({ disableBack, disableNext, isLast, onBack, onNext }) {
  return (
    <div className="flex items-center justify-between pt-2">
      <button
        onClick={onBack}
        disabled={disableBack}
        className={[
          'px-4 py-2 rounded-xl border text-white/90',
          disableBack
            ? 'border-white/15 bg-white/5 opacity-50 cursor-not-allowed'
            : 'border-white/25 bg-white/10 hover:bg-white/15',
        ].join(' ')}
      >
        ← Back
      </button>
      <button
        onClick={onNext}
        disabled={disableNext}
        className={[
          'px-5 py-2 rounded-xl font-medium',
          disableNext ? 'bg-white/30 cursor-not-allowed text-slate-900/60' : 'bg-white text-slate-900 hover:opacity-90',
        ].join(' ')}
      >
        {isLast ? 'Submit' : 'Next →'}
      </button>
    </div>
  )
}

function ProfileStep({ value, onChange, requireContactAtLeastOne = true }) {
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus() }, [])

  const v = value || { anonymous: false, firstName: '', lastName: '', email: '', telegram: '' }
  const set = (patch) => onChange({ ...v, ...patch })

  const disabled = !!v.anonymous

  const emailOk = !v.email || /.+@.+\..+/.test(v.email)
  const needContact = requireContactAtLeastOne && !v.anonymous && !(v.telegram?.trim() || '').length && !(v.email?.trim() || '').length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg md:text-xl font-medium text-white/90">Tell us about yourself</h2>
        <button
          onClick={() => set({ anonymous: !v.anonymous, firstName: '', lastName: '', email: '', telegram: '' })}
          className={[
            'px-3 py-1.5 rounded-lg text-sm border',
            v.anonymous ? 'bg-white text-slate-900 border-white' : 'bg-white/5 text-white/80 border-white/20 hover:bg-white/15',
          ].join(' ')}
          aria-pressed={v.anonymous}
        >
          {v.anonymous ? 'Anonymous ON' : 'Stay Anonymous'}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-white/60 mb-1">Name</label>
          <input
            ref={ref}
            type="text"
            value={v.firstName}
            onChange={(e) => set({ firstName: e.target.value })}
            disabled={disabled}
            placeholder="John"
            className="w-full rounded-xl bg-white/5 border border-white/20 text-white placeholder-white/40 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-white/30 disabled:opacity-60"
          />
        </div>
        <div>
          <label className="block text-xs text-white/60 mb-1">Surname</label>
          <input
            type="text"
            value={v.lastName}
            onChange={(e) => set({ lastName: e.target.value })}
            disabled={disabled}
            placeholder="Doe"
            className="w-full rounded-xl bg-white/5 border border-white/20 text-white placeholder-white/40 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-white/30 disabled:opacity-60"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-white/60 mb-1">Email</label>
          <input
            type="email"
            value={v.email}
            onChange={(e) => set({ email: e.target.value })}
            disabled={disabled}
            placeholder="you@example.com"
            className={[
              'w-full rounded-xl bg-white/5 border text-white placeholder-white/40 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-white/30 disabled:opacity-60',
              emailOk ? 'border-white/20' : 'border-red-400/60',
            ].join(' ')}
          />
          {!emailOk && <div className="mt-1 text-xs text-red-300">Please enter a valid email.</div>}
        </div>
        <div>
          <label className="block text-xs text-white/60 mb-1">Telegram</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40">@</span>
            <input
              type="text"
              value={v.telegram}
              onChange={(e) => set({ telegram: e.target.value.replace(/^@+/, '') })}
              disabled={disabled}
              placeholder="username"
              className="w-full rounded-xl bg-white/5 border border-white/20 text-white placeholder-white/40 pl-7 pr-3 py-2 focus:outline-none focus:ring-2 focus:ring-white/30 disabled:opacity-60"
            />
          </div>
        </div>
      </div>

      {!v.anonymous && (
        <div className="text-xs text-white/60">
          <span className="block">Required: Name & Surname.</span>
          {requireContactAtLeastOne && <span className="block">Also provide at least one contact (Email or Telegram).</span>}
        </div>
      )}

      {needContact && (
        <div className="text-xs text-amber-300">Please provide Email or Telegram (or enable Anonymous).</div>
      )}
    </div>
  )
}

function RatingStep({ question, min = 1, max = 10, value, onChange, onAnswered }) {
  const scale = Array.from({ length: max - min + 1 }, (_, i) => i + min)
  return (
    <div>
      <h2 className="text-lg md:text-xl font-medium text-white/90 mb-4">{question}</h2>
      <div className="flex items-center gap-3 flex-wrap">
        {scale.map((n) => {
          const active = value === n
          return (
            <button
              key={n}
              onClick={() => { onChange(n); if (typeof onAnswered === 'function') onAnswered() }}
              aria-label={`Rate ${n}`}
              className={[
                'h-10 w-10 rounded-full grid place-items-center border transition',
                active
                  ? 'bg-white text-slate-900 border-white shadow'
                  : 'bg-white/5 text-white/80 border-white/20 hover:bg-white/15',
              ].join(' ')}
            >
              {n}
            </button>
          )
        })}
      </div>
      <div className="mt-3 text-xs text-white/50">1 = Low, 10 = High</div>
    </div>
  )
}

function TextStep({ prompt, placeholder = '', minLength = 0, value, onChange }) {
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus() }, [])
  return (
    <div>
      <h2 className="text-lg md:text-xl font-medium text-white/90 mb-3">{prompt}</h2>
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={6}
        className="w-full rounded-xl bg-white/5 border border-white/20 text-white placeholder-white/40 p-4 focus:outline-none focus:ring-2 focus:ring-white/40"
      />
      {minLength > 0 && (
        <div className="mt-2 text-xs text-white/50">Minimum {minLength} character(s).</div>
      )}
    </div>
  )
}

// Basic runtime tests (dev only)
if (typeof window !== 'undefined' && !window.__SURVEYFLOW_TESTS_RAN__) {
  try {
    const answers = {}
    const rb = { id: 'r1', name: 'R', type: 'rating', question: 'q', min: 1, max: 10 }
    console.assert(isBlockValidForAnswers(rb, answers) === false, 'rating: empty invalid')
    answers['r1'] = 7
    console.assert(isBlockValidForAnswers(rb, answers) === true, 'rating: 7 valid')
    answers['r1'] = 0
    console.assert(isBlockValidForAnswers(rb, answers) === false, 'rating: 0 invalid')

    const tb = { id: 't1', name: 'T', type: 'text', prompt: 'p', minLength: 2 }
    console.assert(isBlockValidForAnswers(tb, answers) === false, 'text: empty invalid')
    answers['t1'] = 'ok'
    console.assert(isBlockValidForAnswers(tb, answers) === true, 'text: length 2 valid')

    const pb = { id: 'p1', name: 'P', type: 'profile', requireContactAtLeastOne: true }
    answers['p1'] = { anonymous: true }
    console.assert(isBlockValidForAnswers(pb, answers) === true, 'profile: anonymous valid')

    answers['p1'] = { anonymous: false, firstName: 'A', lastName: 'B', email: '', telegram: 'user' }
    console.assert(isBlockValidForAnswers(pb, answers) === true, 'profile: names + telegram valid')

    answers['p1'] = { anonymous: false, firstName: '', lastName: 'B', email: 'a@b.co', telegram: '' }
    console.assert(isBlockValidForAnswers(pb, answers) === false, 'profile: missing first name invalid')
  } catch (e) {
    // no-op in production
  } finally {
    window.__SURVEYFLOW_TESTS_RAN__ = true
  }
}
