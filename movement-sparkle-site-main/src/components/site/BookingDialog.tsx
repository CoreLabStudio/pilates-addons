import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";

// ── Context ───────────────────────────────────────────────────────────────────

interface BookingDialogCtx {
  openDialog: () => void;
}

const Ctx = React.createContext<BookingDialogCtx | null>(null);

export function useBookingDialog() {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useBookingDialog must be used inside BookingDialogProvider");
  return ctx;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const PORTAL_URL = (import.meta.env.VITE_PORTAL_URL as string) || "";
const TRIAL_ENDPOINT = PORTAL_URL.replace(/\/web\/login$/, "") + "/trial/request";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function detectLang(): string {
  const l = (typeof navigator !== "undefined" ? navigator.language : "") || "";
  if (l.startsWith("ca")) return "ca_ES";
  if (l.startsWith("es")) return "es_ES";
  return "en_US";
}

// ── Types ─────────────────────────────────────────────────────────────────────

type Step = "choice" | "form" | "success";

// ── Inner dialog ──────────────────────────────────────────────────────────────

function BookingDialogInner({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [step, setStep] = React.useState<Step>("choice");
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  // Reset form state after close animation
  React.useEffect(() => {
    if (!open) {
      const t = setTimeout(() => {
        setStep("choice");
        setName("");
        setEmail("");
        setPhone("");
        setNotes("");
        setSubmitError(null);
      }, 300);
      return () => clearTimeout(t);
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    if (!name.trim()) {
      setSubmitError("Please enter your name.");
      return;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setSubmitError("Please enter a valid email address.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(TRIAL_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim(),
          notes: notes.trim(),
          lang: detectLang(),
        }),
      });
      if (!res.ok) throw new Error("Network error — please try again.");
      const json = await res.json() as { success: boolean; error?: string };
      if (!json.success) throw new Error(json.error || "Submission failed.");
      setStep("success");
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-xl border border-border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50";
  const labelClass =
    "block text-xs uppercase tracking-[0.2em] text-muted-foreground mb-1.5";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-2rem)] max-w-md bg-background border border-border rounded-3xl p-8 md:p-10 shadow-2xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 duration-200"
          aria-describedby={undefined}
        >
          {/* Close button */}
          <Dialog.Close className="absolute right-5 top-5 rounded-full p-1.5 text-muted-foreground hover:text-foreground transition-colors focus:outline-none focus:ring-1 focus:ring-accent">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
            <span className="sr-only">Close</span>
          </Dialog.Close>

          {/* ── Choice view ─────────────────────────────────────────────────── */}
          {step === "choice" && (
            <div className="text-center">
              <Dialog.Title asChild>
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-muted-foreground">Welcome</p>
                  <h2 className="mt-3 font-display text-4xl leading-tight">First time here?</h2>
                </div>
              </Dialog.Title>
              <p className="mt-3 text-foreground/70 text-sm leading-relaxed">
                We'd love to meet you properly.
              </p>

              <div className="mt-8 flex flex-col gap-3">
                <button
                  onClick={() => setStep("form")}
                  className="w-full rounded-full bg-accent text-accent-foreground px-6 py-3.5 text-sm hover:opacity-90 transition-opacity text-center"
                >
                  Try a Trial Class
                  <span className="block text-xs opacity-60 mt-0.5">
                    no sign-up needed — we'll arrange the time
                  </span>
                </button>

                <a
                  href={PORTAL_URL}
                  className="w-full rounded-full border border-foreground px-6 py-3.5 text-sm text-center hover:bg-foreground hover:text-background transition-colors block"
                >
                  Skip trial — Book directly
                  <span className="block text-xs opacity-60 mt-0.5">
                    takes you to the member login page
                  </span>
                </a>
              </div>
            </div>
          )}

          {/* ── Form view ───────────────────────────────────────────────────── */}
          {step === "form" && (
            <form onSubmit={handleSubmit} noValidate>
              <button
                type="button"
                onClick={() => setStep("choice")}
                className="mb-5 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                ← Back
              </button>

              <Dialog.Title asChild>
                <h2 className="font-display text-3xl leading-tight">Book a trial class</h2>
              </Dialog.Title>
              <p className="mt-2 text-sm text-foreground/60">
                No account needed. Tell us when you'd like to come.
              </p>

              <div className="mt-6 space-y-4">
                <div>
                  <label htmlFor="td-name" className={labelClass}>
                    Name <span className="text-accent">*</span>
                  </label>
                  <input
                    id="td-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Your full name"
                    className={inputClass}
                    disabled={submitting}
                    autoComplete="name"
                    autoFocus
                  />
                </div>
                <div>
                  <label htmlFor="td-email" className={labelClass}>
                    Email <span className="text-accent">*</span>
                  </label>
                  <input
                    id="td-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className={inputClass}
                    disabled={submitting}
                    autoComplete="email"
                  />
                </div>
                <div>
                  <label htmlFor="td-phone" className={labelClass}>Phone</label>
                  <input
                    id="td-phone"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+351 912 345 678"
                    className={inputClass}
                    disabled={submitting}
                    autoComplete="tel"
                  />
                </div>
                <div>
                  <label htmlFor="td-notes" className={labelClass}>
                    Preferred day / time
                  </label>
                  <textarea
                    id="td-notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder='e.g. "Tuesday mornings" or "flexible — any day works"'
                    rows={2}
                    className={`${inputClass} resize-none`}
                    disabled={submitting}
                  />
                </div>
              </div>

              {submitError && (
                <p className="mt-3 text-sm text-red-500" role="alert">{submitError}</p>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="mt-6 w-full rounded-full bg-accent text-accent-foreground px-6 py-3.5 text-sm hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? "Sending…" : "Send request →"}
              </button>
            </form>
          )}

          {/* ── Success view ─────────────────────────────────────────────────── */}
          {step === "success" && (
            <div className="text-center py-4">
              <div className="mx-auto mb-6 w-12 h-12 rounded-full bg-accent/10 flex items-center justify-center">
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2} className="text-accent" aria-hidden>
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </div>
              <Dialog.Title asChild>
                <h2 className="font-display text-3xl">Request received</h2>
              </Dialog.Title>
              <p className="mt-3 text-foreground/70 text-sm leading-relaxed">
                We'll be in touch soon to confirm your trial class time. Check your inbox for a confirmation email.
              </p>
              <button
                onClick={() => onOpenChange(false)}
                className="mt-8 w-full rounded-full border border-foreground px-6 py-3.5 text-sm hover:bg-foreground hover:text-background transition-colors"
              >
                Close
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function BookingDialogProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);

  const openDialog = React.useCallback(() => setOpen(true), []);

  return (
    <Ctx.Provider value={{ openDialog }}>
      {children}
      <BookingDialogInner open={open} onOpenChange={setOpen} />
    </Ctx.Provider>
  );
}
