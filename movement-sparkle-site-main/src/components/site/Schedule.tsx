import { Reveal } from "./Reveal";
import { WEEKLY_SCHEDULE as days } from "@/lib/schedule-template";

const PORTAL_URL = import.meta.env.VITE_PORTAL_URL as string;

export function Schedule() {
  return (
    <section id="schedule" className="px-6 md:px-10 py-28 md:py-36">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> This week
              </span>
            </Reveal>
            <Reveal
              as="h2"
              delay={1}
              className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]"
            >
              Pick your <span className="italic text-accent font-light">hour.</span>
            </Reveal>
          </div>
          <Reveal delay={2}>
            <a
              href="#contact"
              className="inline-flex items-center gap-3 rounded-full border border-foreground px-6 py-3 text-sm hover:bg-foreground hover:text-background transition-colors"
            >
              See full timetable <span>→</span>
            </a>
          </Reveal>
        </div>

        <div className="mt-14 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-border rounded-3xl overflow-hidden border border-border">
          {days.map((d, i) => (
            <Reveal key={d.day} delay={i} className="bg-background p-7 md:p-8">
              <div className="flex items-baseline justify-between">
                <div className="font-display text-3xl">{d.day}</div>
                <div className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                  Open
                </div>
              </div>
              <ul className="mt-6 space-y-4">
                {d.items.map(([t, c]) => (
                  <li
                    key={t + c}
                    className="flex items-baseline justify-between gap-4 border-b border-border/70 pb-3 last:border-0"
                  >
                    <span className="font-mono text-sm text-accent">{t}</span>
                    <span className="text-sm text-foreground/80">{c}</span>
                    <a
                      href={PORTAL_URL}
                      className="text-xs uppercase tracking-[0.2em] story-link"
                    >
                      Book
                    </a>
                  </li>
                ))}
              </ul>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
