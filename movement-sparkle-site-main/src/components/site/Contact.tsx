import { Reveal } from "./Reveal";
import { useBookingDialog } from "@/components/site/BookingDialog";

export function Contact() {
  const { openDialog } = useBookingDialog();
  return (
    <section id="contact" className="px-6 md:px-10 py-28 md:py-40 bg-foreground text-background">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="text-xs uppercase tracking-[0.32em] text-background/60">
          <span className="inline-flex items-center gap-3">
            <span className="h-px w-8 bg-clay-soft" /> Visit
          </span>
        </Reveal>

        <Reveal as="h2" delay={1} className="mt-6 font-display text-6xl md:text-[9rem] leading-[0.9] tracking-[-0.03em] text-background">
          Come <span className="italic text-clay-soft font-light">breathe</span><br />
          with us.
        </Reveal>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-12">
          <Reveal delay={1}>
            <div className="text-xs uppercase tracking-[0.24em] text-background/60">Studio</div>
            <p className="mt-3 text-lg text-background/90 leading-relaxed">
              Rua da Escola Politécnica 42<br />
              Príncipe Real, 1250-101<br />
              Lisboa, Portugal
            </p>
          </Reveal>
          <Reveal delay={2}>
            <div className="text-xs uppercase tracking-[0.24em] text-background/60">Contact</div>
            <p className="mt-3 text-lg text-background/90 leading-relaxed">
              <span className="text-background/40">[studio email — coming soon]</span><br />
              <span className="text-background/40">[studio phone — coming soon]</span>
            </p>
          </Reveal>
          <Reveal delay={3}>
            <div className="text-xs uppercase tracking-[0.24em] text-background/60">Hours</div>
            <p className="mt-3 text-lg text-background/90 leading-relaxed">
              Mon–Fri · 07:00 – 21:00<br />
              Saturday · 09:00 – 14:00<br />
              Sunday · closed
            </p>
          </Reveal>
        </div>

        <div className="mt-20 flex flex-wrap items-center gap-4">
          <button
            onClick={openDialog}
            className="inline-flex items-center gap-3 rounded-full bg-background text-foreground px-7 py-4 text-sm hover:bg-accent hover:text-background transition-colors"
          >
            Book your first class <span>→</span>
          </button>
          <a
            href="#contact"
            className="inline-flex items-center gap-3 rounded-full border border-background/30 px-7 py-4 text-sm text-background hover:bg-background/10 transition-colors"
          >
            Ask a question
          </a>
        </div>

        <div className="mt-24 border-t border-background/15 pt-8 flex flex-wrap items-center justify-between gap-4 text-xs uppercase tracking-[0.24em] text-background/50">
          <span>© {new Date().getFullYear()} CoreLab</span>
          <div className="flex gap-6">
            <a href="#" className="story-link">Instagram</a>
            <a href="#" className="story-link">Journal</a>
            <a href="#" className="story-link">Privacy</a>
          </div>
        </div>
      </div>
    </section>
  );
}
