import { Reveal } from "./Reveal";
import lounge from "@/assets/detail-lounge.jpg";

const timeline = [
  ["2019", "Two reformers in a borrowed room in Campo de Ourique."],
  ["2021", "Moved into the restored 19th-century building in Príncipe Real."],
  ["2023", "Added the rehab programme and the pre/post-natal cycle."],
  ["2026", "Eight reformers, three teachers, six mats per class — still."],
];

export function Story() {
  return (
    <section id="story" className="px-6 md:px-10 py-28 md:py-36">
      <div className="mx-auto max-w-[1400px] grid grid-cols-1 lg:grid-cols-12 gap-12 items-start">
        <div className="lg:col-span-6">
          <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
            <span className="inline-flex items-center gap-3">
              <span className="h-px w-8 bg-accent" /> Our story
            </span>
          </Reveal>
          <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]">
            Built slowly, <span className="italic text-accent font-light">on purpose.</span>
          </Reveal>
          <Reveal delay={2} className="mt-8 max-w-lg text-lg text-foreground/70 leading-relaxed">
            mōva began as a private practice — one teacher, two reformers, a handful of clients
            recovering from injury. We never set out to build a gym. We set out to build a room
            where the work could be quiet and exact.
          </Reveal>
          <Reveal delay={3} className="mt-6 max-w-lg text-foreground/70 leading-relaxed">
            Seven years later the class cap is still six, the timetable still fits on one page,
            and the teachers still write your name on the board before you arrive.
          </Reveal>

          <div className="mt-12">
            {timeline.map(([y, t], i) => (
              <Reveal key={y} delay={i}>
                <div className="flex gap-8 border-t border-border py-5">
                  <span className="font-mono text-sm text-accent w-14 shrink-0">{y}</span>
                  <span className="text-foreground/80">{t}</span>
                </div>
              </Reveal>
            ))}
          </div>
        </div>

        <Reveal delay={2} className="lg:col-span-6">
          <div className="img-cover-zoom overflow-hidden rounded-[2rem] aspect-[7/5] bg-muted">
            <img
              src={lounge}
              alt="The mōva studio lounge with folded towels and coffee"
              loading="lazy"
              width={1400}
              height={1000}
              className="w-full h-full object-cover"
            />
          </div>
          <div className="mt-8 grid grid-cols-2 gap-6">
            {[
              ["1,400+", "Classes taught last year"],
              ["94%", "Members who stay past 6 months"],
              ["3", "Teachers, all 450h+ certified"],
              ["0", "Mirrors on the walls"],
            ].map(([n, l]) => (
              <div key={l} className="border-t border-border pt-5">
                <div className="font-display text-4xl md:text-5xl">{n}</div>
                <div className="mt-2 text-sm text-muted-foreground">{l}</div>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
