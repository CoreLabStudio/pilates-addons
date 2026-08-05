import { Reveal } from "./Reveal";

const plans = [
  {
    name: "Barre",
    price: "€10",
    unit: "trial class",
    desc: "Start with a single session, build the habit with a pack.",
    perks: [
      "Trial class: €10",
      "Single class: €19",
      "5-class pack: €90 · valid 60 days",
      "10-class pack: €150 · valid 60 days",
      "Monthly from €75",
    ],
    featured: false,
  },
  {
    name: "Reformer",
    price: "€15",
    unit: "trial class",
    desc: "Your first session at a special rate — then build with packs or a fixed weekly rhythm.",
    perks: [
      "Trial class: €15",
      "Single class: €25",
      "Intro 3-class bono: €60 · valid 15 days",
      "5-class pack: €120 · valid 90 days",
      "10-class pack: €230 · valid 90 days",
      "15-class pack: €330 · valid 90 days",
    ],
    featured: true,
  },
  {
    name: "Monthly",
    price: "€75",
    unit: "/ month",
    desc: "Fix a slot each week. Build the habit with a reserved place in every class.",
    perks: [
      "Barre Clase Fija 1×: €75 / mo",
      "Barre Clase Fija 2×: €140 / mo",
      "Barre Ilimitado: €200 / mo",
      "Reformer 1×/week: €80 / mo",
      "Reformer 2×/week: €150 / mo",
      "Reformer 3×/week: €210 / mo",
    ],
    featured: false,
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="px-6 md:px-10 py-28 md:py-36 bg-secondary/40">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
          <span className="inline-flex items-center gap-3">
            <span className="h-px w-8 bg-accent" /> Memberships
          </span>
        </Reveal>
        <div className="mt-6 flex items-end justify-between flex-wrap gap-6">
          <Reveal as="h2" delay={1} className="font-display text-5xl md:text-7xl leading-[0.95]">
            Simple ways to <span className="italic text-accent font-light">stay.</span>
          </Reveal>
          <Reveal delay={2} className="max-w-sm text-foreground/70">
            No contracts, no joining fee. First Reformer class €15, first Barre class €10 — try the machine before committing.
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6">
          {plans.map((p, i) => (
            <Reveal key={p.name} delay={i + 1}>
              <div
                className={`h-full flex flex-col rounded-[1.75rem] border p-8 md:p-10 hover-lift ${
                  p.featured
                    ? "border-accent bg-background shadow-[0_30px_60px_-40px_rgba(0,0,0,0.35)]"
                    : "border-border bg-background"
                }`}
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-display text-2xl md:text-3xl">{p.name}</h3>
                  {p.featured && (
                    <span className="rounded-full bg-accent/10 text-accent text-[10px] uppercase tracking-[0.24em] px-3 py-1">
                      Popular
                    </span>
                  )}
                </div>
                <div className="mt-6 flex items-baseline gap-2">
                  <span className="font-display text-5xl md:text-6xl">{p.price}</span>
                  <span className="text-sm text-muted-foreground">{p.unit}</span>
                </div>
                <p className="mt-4 text-foreground/70 leading-relaxed">{p.desc}</p>
                <ul className="mt-6 space-y-3 text-sm text-foreground/80">
                  {p.perks.map((k) => (
                    <li key={k} className="flex items-start gap-3 border-b border-border/70 pb-3 last:border-0">
                      <span className="text-accent">—</span>
                      {k}
                    </li>
                  ))}
                </ul>
                <a
                  href="#contact"
                  className={`mt-8 inline-flex items-center justify-center gap-2 rounded-full px-6 py-3.5 text-sm transition-colors ${
                    p.featured
                      ? "bg-accent text-accent-foreground hover:opacity-90"
                      : "border border-foreground hover:bg-foreground hover:text-background"
                  }`}
                >
                  Choose {p.name} <span>→</span>
                </a>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
