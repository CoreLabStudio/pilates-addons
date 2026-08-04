import { Reveal } from "./Reveal";
import j1 from "@/assets/journal-1.jpg";
import j2 from "@/assets/journal-2.jpg";
import j3 from "@/assets/journal-3.jpg";

const posts = [
  {
    img: j1,
    cat: "Technique",
    date: "12 July 2026",
    read: "5 min",
    title: "Why we teach the footbar before the straps",
    excerpt:
      "Feet first, always. A short piece on how the lower body organises everything that happens above it.",
  },
  {
    img: j2,
    cat: "Breath",
    date: "28 June 2026",
    read: "4 min",
    title: "The exhale is the exercise",
    excerpt:
      "Most people hold their breath at the hardest moment. Here's the simple pattern we coach instead.",
  },
  {
    img: j3,
    cat: "Studio",
    date: "09 June 2026",
    read: "6 min",
    title: "Notes from the Slow Sunday retreat",
    excerpt:
      "Twelve people, two sessions and a long lunch. What we learned about pacing a whole day of practice.",
  },
];

export function Journal() {
  return (
    <section id="journal" className="px-6 md:px-10 py-28 md:py-36">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> Journal
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]">
              Words between <span className="italic text-accent font-light">classes.</span>
            </Reveal>
          </div>
          <Reveal delay={2}>
            <a
              href="#contact"
              className="inline-flex items-center gap-3 rounded-full border border-foreground px-6 py-3 text-sm hover:bg-foreground hover:text-background transition-colors"
            >
              Read the journal <span>→</span>
            </a>
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8">
          {posts.map((p, i) => (
            <Reveal key={p.title} delay={i + 1}>
              <a href="#journal" className="group block">
                <div className="img-cover-zoom overflow-hidden rounded-[1.75rem] aspect-[7/5] bg-muted">
                  <img
                    src={p.img}
                    alt={p.title}
                    loading="lazy"
                    width={1400}
                    height={1000}
                    className="w-full h-full object-cover"
                  />
                </div>
                <div className="mt-5 flex items-center gap-3 text-xs uppercase tracking-[0.22em] text-muted-foreground">
                  <span className="text-accent">{p.cat}</span>
                  <span className="h-px w-6 bg-border" />
                  <span>{p.date}</span>
                  <span className="h-px w-6 bg-border" />
                  <span>{p.read}</span>
                </div>
                <h3 className="mt-3 font-display text-2xl md:text-3xl leading-tight">{p.title}</h3>
                <p className="mt-3 text-foreground/70">{p.excerpt}</p>
                <div className="mt-4 inline-flex items-center gap-2 text-sm text-accent">
                  <span className="story-link">Read</span>
                  <span className="transition-transform group-hover:translate-x-1">→</span>
                </div>
              </a>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
