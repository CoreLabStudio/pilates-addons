import { motion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { Reveal } from "./Reveal";
import warm from "@/assets/studio-warm.jpg";

export function Studio() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], ["-8%", "8%"]);
  const scale = useTransform(scrollYProgress, [0, 0.5, 1], [1.05, 1, 1.05]);

  return (
    <section id="studio" className="px-6 md:px-10 py-24 md:py-36">
      <div className="mx-auto max-w-[1400px]">
        <div
          ref={ref}
          className="relative overflow-hidden rounded-[2.5rem] aspect-[16/9] md:aspect-[21/9]"
        >
          <motion.img
            src={warm}
            alt="Golden hour inside the CoreLab studio"
            loading="lazy"
            width={1600}
            height={1200}
            style={{ y, scale }}
            className="absolute inset-0 w-full h-[115%] object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-ink/70 via-ink/10 to-transparent" />
          <div className="relative h-full flex flex-col justify-end p-8 md:p-14 text-background">
            <Reveal className="text-xs uppercase tracking-[0.32em] text-background/80">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-clay-soft" /> The space
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-4 font-display text-4xl md:text-7xl max-w-3xl leading-[1] text-background">
              Warm wood, golden light, <span className="italic text-clay-soft font-light">room to breathe.</span>
            </Reveal>
            <Reveal delay={2} className="mt-5 max-w-lg text-background/80">
              Housed in a restored 19th-century building, our studio was designed as
              a slow room — high ceilings, arched windows, plants that keep growing.
            </Reveal>
          </div>
        </div>

        <div className="mt-12 grid grid-cols-2 md:grid-cols-4 gap-6 md:gap-10">
          {[
            ["8", "Reformer beds"],
            ["6", "Mats per class"],
            ["12", "Weekly classes"],
            ["1", "Very good coffee"],
          ].map(([n, l], i) => (
            <Reveal key={l} delay={i}>
              <div className="border-t border-border pt-5">
                <div className="font-display text-5xl md:text-6xl">{n}</div>
                <div className="mt-2 text-sm uppercase tracking-[0.2em] text-muted-foreground">{l}</div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
