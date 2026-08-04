import { Reveal } from "./Reveal";

const quotes = [
  {
    q: "I came for a stronger back and left with a slower mind. mōva changed my whole week.",
    n: "Inês C.",
    r: "Member since 2022",
  },
  {
    q: "The teaching is unreal. Six mats, no music louder than the reformer springs. Just work.",
    n: "David M.",
    r: "Reformer Flow",
  },
  {
    q: "It's the only class I actually protect on my calendar.",
    n: "Sara P.",
    r: "Private 1:1",
  },
];

export function Testimonials() {
  return (
    <section className="px-6 md:px-10 py-28 md:py-36 bg-secondary/40">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
          <span className="inline-flex items-center gap-3">
            <span className="h-px w-8 bg-accent" /> In their words
          </span>
        </Reveal>
        <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-8">
          {quotes.map((t, i) => (
            <Reveal key={t.n} delay={i}>
              <figure className="h-full flex flex-col justify-between rounded-[1.75rem] border border-border bg-background p-8">
                <blockquote className="font-display text-2xl md:text-3xl leading-[1.15] tracking-tight">
                  <span className="text-accent">“</span>
                  {t.q}
                  <span className="text-accent">”</span>
                </blockquote>
                <figcaption className="mt-10 flex items-baseline justify-between text-sm">
                  <span className="font-medium">{t.n}</span>
                  <span className="text-muted-foreground">{t.r}</span>
                </figcaption>
              </figure>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
