import { Reveal } from "./Reveal";
import t1 from "@/assets/teacher-1.jpg";
import t2 from "@/assets/teacher-2.jpg";
import t3 from "@/assets/teacher-3.jpg";

const team = [
  {
    name: "Marta Vieira",
    role: "Founder · Reformer",
    bio: "Fifteen years of classical training and a physiotherapy background. Marta teaches the slow, precise work that the studio was built on.",
    img: t1,
    cert: "BASI · 500h",
  },
  {
    name: "Tomás Leal",
    role: "Mat & Props",
    bio: "Former dancer turned teacher. Tomás sequences with musicality — long spirals, deep breath, no rushing.",
    img: t2,
    cert: "Polestar · 450h",
  },
  {
    name: "Sofia Andrade",
    role: "Private 1:1 · Rehab",
    bio: "Works with post-injury and pre/post-natal clients. Every programme is written for one body only.",
    img: t3,
    cert: "APPI Clinical",
  },
];

export function Teachers() {
  return (
    <section id="teachers" className="px-6 md:px-10 py-28 md:py-36">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> The teachers
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]">
              Taught by people who <span className="italic text-accent font-light">notice.</span>
            </Reveal>
          </div>
          <Reveal delay={2} className="max-w-sm text-foreground/70">
            Three teachers, one language. We meet weekly to review programming so your practice stays coherent across the timetable.
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8">
          {team.map((p, i) => (
            <Reveal key={p.name} delay={i + 1}>
              <article className="group">
                <div className="img-cover-zoom overflow-hidden rounded-[1.75rem] aspect-[4/5] bg-muted">
                  <img
                    src={p.img}
                    alt={`${p.name}, ${p.role}`}
                    loading="lazy"
                    width={1000}
                    height={1250}
                    className="w-full h-full object-cover"
                  />
                </div>
                <div className="mt-5 flex items-baseline justify-between gap-4">
                  <h3 className="font-display text-2xl md:text-3xl">{p.name}</h3>
                  <span className="text-xs uppercase tracking-[0.24em] text-muted-foreground shrink-0">
                    {p.cert}
                  </span>
                </div>
                <div className="mt-1 text-sm text-accent">{p.role}</div>
                <p className="mt-3 text-foreground/70 leading-relaxed">{p.bio}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
