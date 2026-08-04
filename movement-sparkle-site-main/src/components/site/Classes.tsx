import { Reveal } from "./Reveal";
import reformer from "@/assets/class-reformer.jpg";
import mat from "@/assets/class-mat.jpg";
import priv from "@/assets/class-private.jpg";
import springs from "@/assets/detail-springs.jpg";

const classes = [
  {
    name: "Reformer Flow",
    tag: "Group · 50 min",
    desc: "Our signature class. Fluid sequences on the reformer that balance strength and length.",
    img: reformer,
    level: "All levels",
    focus: "Full body · springs medium",
  },
  {
    name: "Mat & Props",
    tag: "Group · 50 min",
    desc: "Classical mat work layered with rings, balls and bands. Deep core, light equipment.",
    img: mat,
    level: "All levels",
    focus: "Core · mobility",
  },
  {
    name: "Slow Reformer",
    tag: "Group · 55 min",
    desc: "Half the tempo, twice the awareness. Long holds, heavy springs and a lot of breath.",
    img: springs,
    level: "Beginner friendly",
    focus: "Control · alignment",
  },
  {
    name: "Private 1:1",
    tag: "Private · 55 min",
    desc: "A programme built to your body, your goals and the way you already move.",
    img: priv,
    level: "Any body",
    focus: "Rehab · pre/post-natal",
  },
];

const PORTAL_URL = import.meta.env.VITE_PORTAL_URL as string;

export function Classes() {
  return (
    <section id="classes" className="px-6 md:px-10 py-28 md:py-36 bg-secondary/40">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> Classes
              </span>
            </Reveal>
            <Reveal
              as="h2"
              delay={1}
              className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]"
            >
              Four ways to <span className="italic text-accent font-light">meet</span> your
              practice.
            </Reveal>
          </div>
          <Reveal delay={2} className="max-w-sm text-foreground/70">
            All levels welcome. New to reformer? Start with a private or Slow Reformer, then join
            the flow.
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {classes.map((c, i) => {
            const isPrivate = c.tag.startsWith("Private");
            const cardBody = (
              <>
                <div className="img-cover-zoom overflow-hidden rounded-[1.75rem] aspect-[4/5] bg-muted">
                  <img
                    src={c.img}
                    alt={c.name}
                    loading="lazy"
                    width={1200}
                    height={1500}
                    className="w-full h-full object-cover"
                  />
                </div>
                <div className="mt-5 flex items-baseline justify-between gap-4">
                  <h3 className="font-display text-2xl md:text-3xl">{c.name}</h3>
                  <span className="text-xs uppercase tracking-[0.24em] text-muted-foreground shrink-0">
                    {c.tag}
                  </span>
                </div>
                <p className="mt-3 text-foreground/70">{c.desc}</p>
                <dl className="mt-4 space-y-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  <div className="flex justify-between gap-4 border-t border-border pt-2">
                    <dt>Level</dt>
                    <dd className="text-foreground/80 normal-case tracking-normal text-sm">
                      {c.level}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 border-t border-border pt-2">
                    <dt>Focus</dt>
                    <dd className="text-foreground/80 normal-case tracking-normal text-sm">
                      {c.focus}
                    </dd>
                  </div>
                </dl>
                <div className="mt-4 inline-flex items-center gap-2 text-sm text-accent">
                  <span className="story-link">{isPrivate ? "Enquire" : "Book this class"}</span>
                  <span className="transition-transform group-hover:translate-x-1">→</span>
                </div>
              </>
            );

            return (
              <Reveal key={c.name} delay={i + 1}>
                {isPrivate ? (
                  <a href="#contact" className="group block">
                    {cardBody}
                  </a>
                ) : (
                  <a href={PORTAL_URL} className="group block">
                    {cardBody}
                  </a>
                )}
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}
