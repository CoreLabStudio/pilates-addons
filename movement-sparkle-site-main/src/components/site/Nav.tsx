import { motion } from "motion/react";
import corelabLogo from "@/assets/corelab-logo-header.png";
import { useBookingDialog } from "@/components/site/BookingDialog";

const links = [
  { label: "Method", href: "#method" },
  { label: "Classes", href: "#classes" },
  { label: "Studio", href: "#studio" },
  { label: "Teachers", href: "#teachers" },
  { label: "Schedule", href: "#schedule" },
  { label: "Workshops", href: "#workshops" },
  { label: "Pricing", href: "#pricing" },
  { label: "Journal", href: "#journal" },
];



export function Nav() {
  const { openDialog } = useBookingDialog();
  return (
    <motion.header
      initial={{ y: -40, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 inset-x-0 z-50 px-6 md:px-10 pt-5"
    >
      <div className="mx-auto max-w-[1400px] flex items-center justify-between rounded-full border border-border/70 bg-background/70 backdrop-blur-xl px-6 md:px-8 py-3.5 shadow-[0_1px_0_rgba(0,0,0,0.02),0_20px_40px_-30px_rgba(0,0,0,0.25)]">
        <a href="#top" className="flex items-center group">
          <img src={corelabLogo} alt="CoreLab" className="h-12 w-auto" />
        </a>

        <nav className="hidden lg:flex items-center gap-5 xl:gap-7 text-sm">
          {links.map((l) => (
            <a key={l.href} href={l.href} className="story-link text-foreground/80 hover:text-foreground">
              {l.label}
            </a>
          ))}
        </nav>

        <button
          onClick={openDialog}
          className="group inline-flex items-center gap-2 rounded-full bg-accent text-accent-foreground px-5 py-2.5 text-sm hover:opacity-90 transition-opacity"
        >
          Book a class
          <span className="inline-block transition-transform group-hover:translate-x-0.5">→</span>
        </button>
      </div>
    </motion.header>
  );
}
