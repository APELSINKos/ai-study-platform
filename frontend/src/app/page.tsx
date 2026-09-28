import { SiteHeader } from "@/components/site-header";
import { ClosingCta } from "@/features/landing/closing-cta";
import { Hero } from "@/features/landing/hero/hero";
import { HowItWorks } from "@/features/landing/how-it-works/how-it-works";
import { Practice } from "@/features/landing/practice/practice";
import { RememberLonger } from "@/features/landing/remember/remember-longer";
import { SiteFooter } from "@/features/landing/site-footer";

export default function LandingPage() {
  return (
    // `clip` rather than `hidden`: it stops sideways scrolling without breaking sticky pinning.
    <div className="overflow-x-clip px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-6xl">
        <SiteHeader />
        {/* The sections share the notebook's two columns, so margin notes line up with the rule. */}
        <main className="col-span-full grid grid-cols-subgrid">
          <Hero />
          <HowItWorks />
          <Practice />
          <RememberLonger />
          <ClosingCta />
        </main>
        <SiteFooter />
      </div>
    </div>
  );
}
