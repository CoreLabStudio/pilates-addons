import { Reveal } from "./Reveal";

const press = ["Time Out Lisboa", "Monocle", "Vogue Portugal", "Kinfolk", "Público"];

export function Newsletter() {
  return (
    <section className="px-6 md:px-10 py-24 md:py-32 bg-secondary/40">
      <div className="mx-auto max-w-[1400px]">
        <div className="rounded-[2rem] border border-border bg-background p-8 md:p-14 grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
          <div className="lg:col-span-6">
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> Letters
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-5 font-display text-4xl md:text-6xl leading-[0.98]">
              One letter a month. <span className="italic text-accent font-light">No noise.</span>
            </Reveal>
            <Reveal delay={2} className="mt-5 max-w-md text-foreground/70">
              New workshop dates, a short note on technique, and the occasional playlist. Unsubscribe in one click.
            </Reveal>
          </div>

          <Reveal delay={3} className="lg:col-span-6">
            <form
              className="flex flex-col sm:flex-row gap-3"
              onSubmit={(e) => e.preventDefault()}
            >
              <label htmlFor="newsletter-email" className="sr-only">
                Email address
              </label>
              <input
                id="newsletter-email"
                type="email"
                required
                placeholder="you@email.com"
                className="flex-1 rounded-full border border-border bg-background px-6 py-4 text-sm outline-none transition-colors focus:border-accent"
              />
              <button
                type="submit"
                className="inline-flex items-center justify-center gap-2 rounded-full bg-foreground text-background px-7 py-4 text-sm transition-colors hover:bg-accent"
              >
                Subscribe <span>→</span>
              </button>
            </form>
            <p className="mt-3 text-xs text-muted-foreground">
              We keep your address to ourselves. Always.
            </p>
          </Reveal>
        </div>

        <div className="mt-16 flex flex-wrap items-center justify-center gap-x-12 gap-y-6">
          {press.map((p, i) => (
            <Reveal key={p} delay={i}>
              <span className="font-display text-xl md:text-2xl text-muted-foreground/70">{p}</span>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
