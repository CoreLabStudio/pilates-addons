import { Reveal } from "./Reveal";

const faqs = [
  {
    q: "I've never done reformer. Where do I start?",
    a: "Book an intro private or the Slow Reformer class. We'll walk you through the carriage, the springs and the safety basics before you join a flow.",
  },
  {
    q: "What should I wear and bring?",
    a: "Fitted clothing you can move in and grip socks — we keep spare pairs at reception. Towels and filtered water are on us.",
  },
  {
    q: "How far in advance can I book?",
    a: "Two weeks ahead. Classes cap at six mats, so popular hours fill fast; the waitlist usually clears within a day.",
  },
  {
    q: "What's the cancellation policy?",
    a: "Free cancellation up to 8 hours before class. Inside that window the credit is used, so the mat can be released to the waitlist in time.",
  },
  {
    q: "Can I train while pregnant or after an injury?",
    a: "Yes — with a private assessment first. Sofia writes pre/post-natal and rehab programmes and will coordinate with your physio if you'd like.",
  },
];

export function Faq() {
  return (
    <section id="faq" className="px-6 md:px-10 py-28 md:py-36 bg-secondary/40">
      <div className="mx-auto max-w-[1400px] grid grid-cols-1 lg:grid-cols-12 gap-12">
        <div className="lg:col-span-4">
          <Reveal className="text-xs uppercase tracking-[0.32em] text-muted-foreground">
            <span className="inline-flex items-center gap-3">
              <span className="h-px w-8 bg-accent" /> Good to know
            </span>
          </Reveal>
          <Reveal as="h2" delay={1} className="mt-6 font-display text-5xl md:text-6xl leading-[0.95]">
            Before your <span className="italic text-accent font-light">first</span> class.
          </Reveal>
          <Reveal delay={2} className="mt-6 text-foreground/70">
            Still unsure about something? Write to us — a real person answers, usually the same day.
          </Reveal>
        </div>

        <div className="lg:col-span-8">
          {faqs.map((f, i) => (
            <Reveal key={f.q} delay={i}>
              <details className="group border-b border-border py-6">
                <summary className="flex cursor-pointer items-start justify-between gap-6 list-none">
                  <span className="font-display text-2xl md:text-3xl leading-tight">{f.q}</span>
                  <span className="mt-1 text-accent transition-transform duration-300 group-open:rotate-45">
                    +
                  </span>
                </summary>
                <p className="mt-4 max-w-2xl text-foreground/70 leading-relaxed">{f.a}</p>
              </details>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
