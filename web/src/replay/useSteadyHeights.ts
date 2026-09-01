import { useEffect } from "react";

/**
 * Stop the board shrinking under the reader.
 *
 * A replay accumulates: gate rows land, the ledger tail fills, a diagnosis appears. Each of those
 * changes a section's height, and a section changing height moves everything below it. Measured
 * over one run the page went from 3417px to 5702px and changed height 63 times, and every one of
 * those changes moved whatever the reader was looking at.
 *
 * Growth on its own is tolerable, because it happens below the thing being read and reads as the
 * run producing something. What does not is a section shrinking and then growing again, which is
 * the page jumping up and down under a still cursor.
 *
 * So each section keeps the tallest it has been for this run as a floor. It can grow, it cannot
 * fall back, and the floor is cleared when the run restarts or the recording changes. Nothing is
 * hidden and nothing is capped: a section that has more to show still shows it.
 */
export function useSteadyHeights(container: string, resetKey: unknown): void {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(container);
    if (!root) return undefined;

    const floors = new WeakMap<HTMLElement, number>();
    const sections = () => root.querySelectorAll<HTMLElement>("section.section");

    // A fresh run starts with no floors, so a restart does not inherit the last run's tallest.
    sections().forEach((section) => {
      section.style.minHeight = "";
    });

    let frame = 0;
    const hold = () => {
      sections().forEach((section) => {
        // Measured without the floor's own contribution: `scrollHeight` is the content, so a
        // section whose content has genuinely shrunk does not keep inflating its own floor.
        const natural = section.scrollHeight;
        const floor = floors.get(section) ?? 0;
        if (natural > floor) {
          floors.set(section, natural);
          section.style.minHeight = `${natural}px`;
        }
      });
      frame = window.requestAnimationFrame(hold);
    };
    frame = window.requestAnimationFrame(hold);

    return () => {
      window.cancelAnimationFrame(frame);
      sections().forEach((section) => {
        section.style.minHeight = "";
      });
    };
  }, [container, resetKey]);
}
