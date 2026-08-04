import { Reveal } from "./Reveal";
import plants from "@/assets/detail-plants.jpg";

const pillars = [
  { n: "01", t: "Precision", d: "Every repetition is coached. Alignment first, intensity second." },
  { n: "02", t: "Small groups", d: "Six mats per class. Your instructor knows your body." },
  { n: "03", t: "Slow tempo", d: "Time under tension over time on the clock. Progress that lasts." },
  { n: "04", t: "Whole body", d: "Reformer, mat and props sequenced across the week." },
];


export function Method() {
  return (
    <section id="method" className="px-6 md:px-10 py-28 md:py-40">
      <div className="mx-auto max-w-[1400px] grid grid-cols-1 lg:grid-cols-12 gap-12">
        <div className="lg:col-span-5">
          <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
            <span className="inline-flex items-center gap-3">
              <span className="h-px w-8 bg-accent" /> The method
            </span>
          </Reveal>
          <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95] tracking-tight">
            A practice that <span className="italic text-accent font-light">quiets</span> the noise.
          </Reveal>
          <Reveal delay={2} className="mt-8 max-w-md text-foreground/70 text-lg">
            We don't chase intensity. We build strength you can feel in the small things —
            the way you sit, breathe, reach, carry the weight of a day.
          </Reveal>
          <Reveal delay={3} className="mt-10 img-cover-zoom overflow-hidden rounded-[1.75rem] aspect-[4/5] bg-muted max-w-md">
            <img
              src={plants}
              alt="Arched studio window with plants in warm afternoon light"
              loading="lazy"
              width={1200}
              height={1500}
              className="w-full h-full object-cover"
            />
          </Reveal>
          <Reveal delay={4} className="mt-8 max-w-md space-y-4 text-foreground/70">
            <p>
              Each term follows a theme — hips, shoulder girdle, spinal rotation — so the work
              compounds instead of resetting every week.
            </p>
            <p className="text-sm uppercase tracking-[0.22em] text-muted-foreground">
              Six mats · Two teachers per week · Twelve-week cycles
            </p>
          </Reveal>
        </div>

        <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-2 gap-px bg-border rounded-3xl overflow-hidden">
          {pillars.map((p, i) => (
            <Reveal
              key={p.n}
              delay={i + 1}
              className="bg-background p-8 md:p-10 hover-lift"
            >
              <div className="text-accent font-display text-2xl">{p.n}</div>
              <h3 className="mt-6 font-display text-2xl md:text-3xl">{p.t}</h3>
              <p className="mt-3 text-foreground/70 leading-relaxed">{p.d}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
