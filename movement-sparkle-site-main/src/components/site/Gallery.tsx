import { Reveal } from "./Reveal";
import springs from "@/assets/detail-springs.jpg";
import plants from "@/assets/detail-plants.jpg";
import lounge from "@/assets/detail-lounge.jpg";
import mat from "@/assets/class-mat.jpg";

const shots = [
  { src: plants, alt: "Arched window and plants in the studio corner", cap: "Arched light, morning", span: "md:col-span-4 aspect-[4/5]" },
  { src: lounge, alt: "Towels and coffee in the studio lounge", cap: "The lounge — coffee after class", span: "md:col-span-8 aspect-[16/10]" },
  { src: springs, alt: "Close-up of reformer springs and straps", cap: "Springs, checked every week", span: "md:col-span-7 aspect-[16/10]" },
  { src: mat, alt: "Mat work with props in the studio", cap: "Mat & props, Tuesday 07:00", span: "md:col-span-5 aspect-[4/5]" },
];

export function Gallery() {
  return (
    <section id="gallery" className="px-6 md:px-10 py-28 md:py-36">
      <div className="mx-auto max-w-[1400px]">
        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
              <span className="inline-flex items-center gap-3">
                <span className="h-px w-8 bg-accent" /> Inside
              </span>
            </Reveal>
            <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-7xl leading-[0.95]">
              A room made of <span className="italic text-accent font-light">small things.</span>
            </Reveal>
          </div>
          <Reveal delay={2} className="max-w-sm text-foreground/70">
            Linen towels, filtered water, a kettle that is always on. The details are the hospitality.
          </Reveal>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-12 gap-6">
          {shots.map((s, i) => (
            <Reveal key={s.cap} delay={i} className={s.span}>
              <figure className="h-full">
                <div className="img-cover-zoom overflow-hidden rounded-[1.75rem] h-full bg-muted">
                  <img
                    src={s.src}
                    alt={s.alt}
                    loading="lazy"
                    width={1200}
                    height={1200}
                    className="w-full h-full object-cover"
                  />
                </div>
                <figcaption className="mt-3 text-xs uppercase tracking-[0.24em] text-muted-foreground">
                  {s.cap}
                </figcaption>
              </figure>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
