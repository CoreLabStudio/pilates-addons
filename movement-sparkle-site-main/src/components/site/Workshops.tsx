import { Reveal } from "./Reveal";

const events = [
  {
    date: "14 Sep",
    title: "Breath & Spine",
    len: "3 hours",
    price: "€65",
    desc: "A half-day on rotation, breath mechanics and why your ribs matter more than your abs.",
    spots: "4 places left",
  },
  {
    date: "05 Oct",
    title: "Reformer Foundations",
    len: "2 × 90 min",
    price: "€90",
    desc: "A two-part intensive for beginners: springs, safety, and the eight shapes we return to.",
    spots: "Open",
  },
  {
    date: "19 Oct",
    title: "Pre & Post-Natal Lab",
    len: "2 hours",
    price: "€55",
    desc: "With Sofia and a visiting pelvic-health physio. Practical, unhurried, questions welcome.",
    spots: "6 places left",
  },
  {
    date: "09 Nov",
    title: "Slow Sunday Retreat",
    len: "Half day",
    price: "€120",
    desc: "Two sessions, a long breathwork hour and lunch from the bakery on the corner.",
    spots: "Waitlist",
  },
];

export function Workshops() {
  return (
    <section id="workshops" className="px-6 md:px-10 py-28 md:py-36 bg-secondary/40">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> Workshops
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]">
              Go <span className="italic text-accent font-light">deeper</span> for an afternoon.
            </Reveal>
          </div>
          <Reveal delay={2} className="max-w-sm text-foreground/70">
            Small-format sessions with the teachers and occasional guests. Members get 10% off every date.
          </Reveal>
        </div>

        <div className="mt-14 rounded-3xl border border-border overflow-hidden bg-background">
          {events.map((e, i) => (
            <Reveal key={e.title} delay={i}>
              <a
                href="#contact"
                className="group grid grid-cols-1 md:grid-cols-12 gap-4 md:gap-6 items-baseline px-7 md:px-10 py-8 border-b border-border last:border-0 transition-colors hover:bg-secondary/50"
              >
                <div className="md:col-span-2 font-mono text-sm text-accent">{e.date}</div>
                <div className="md:col-span-4">
                  <h3 className="font-display text-2xl md:text-3xl">{e.title}</h3>
                  <div className="mt-1 text-xs uppercase tracking-[0.22em] text-muted-foreground">
                    {e.len} · {e.price}
                  </div>
                </div>
                <p className="md:col-span-4 text-foreground/70">{e.desc}</p>
                <div className="md:col-span-2 flex items-center justify-between md:justify-end gap-3 text-sm">
                  <span className="text-muted-foreground">{e.spots}</span>
                  <span className="transition-transform group-hover:translate-x-1 text-accent">→</span>
                </div>
              </a>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
