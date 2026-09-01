import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Replay } from "../../replay/model";
import { holdMsFor, markFor, type Mark } from "../../replay/commentary";

/**
 * The commentary layer.
 *
 * A coach mark that appears when the head reaches a beat, points at the region the beat is about,
 * says one sentence and leaves. It never pauses the run, never asks for a click, and never moves
 * the scrub position. Turning it off is the only control it has.
 *
 * One mark at a time. Beats in this recording arrive in clusters sharing a single sim second, five
 * of them at the moment the incident opens, and five panels shouting at once is worse than nothing.
 * A beat that lands while a mark is up joins a queue and waits its turn.
 *
 * The queue is not capped. It was, at three, and that quietly dropped the diagnosis and the two
 * case-table outcomes because they arrived in the middle of a cluster: a beat worth stopping on is
 * worth saying something about, even a few seconds late. Fourteen beats is the whole recording, so
 * the queue cannot grow beyond that.
 */

const FADE_MS = 200;

interface Placement {
  top: number;
  left: number;
  /** Where the leader meets the region, in viewport coordinates. */
  leaderTop: number;
  leaderLeft: number;
  leaderWidth: number;
}

export function Commentary({
  replay,
  ord,
  enabled,
}: {
  replay: Replay;
  ord: number;
  enabled: boolean;
}) {
  const [current, setCurrent] = useState<Mark | null>(null);
  const [visible, setVisible] = useState(false);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const queue = useRef<Mark[]>([]);
  const shown = useRef<Set<number>>(new Set());
  const lastOrd = useRef(ord);
  const panel = useRef<HTMLDivElement | null>(null);

  // Collect the beats the head has just crossed. Reading the span between the last cursor and this
  // one catches a jump as well as a step, so scrubbing does not silently skip the commentary for
  // everything it passed over.
  useEffect(() => {
    if (!enabled) return;
    const from = lastOrd.current;
    lastOrd.current = ord;
    if (ord <= from) return;
    for (let index = from + 1; index <= ord; index += 1) {
      const frame = replay.frames[index];
      if (!frame || !frame.held) continue;
      if (shown.current.has(frame.ord)) continue;
      const mark = markFor(replay, frame);
      if (!mark) continue;
      shown.current.add(frame.ord);
      queue.current.push(mark);
    }
  }, [ord, replay, enabled]);

  // Drain the queue, one mark at a time.
  useEffect(() => {
    if (!enabled || current) return;
    const next = queue.current.shift();
    if (!next) {
      // Nothing waiting. Look again shortly rather than subscribing the queue to render.
      const idle = window.setTimeout(() => setCurrent(null), 160);
      return () => window.clearTimeout(idle);
    }
    setCurrent(next);
    return undefined;
  }, [current, enabled, ord]);

  // Hold, then fade, then release the slot.
  useEffect(() => {
    if (!current) return;
    setVisible(true);
    const hold = window.setTimeout(() => setVisible(false), holdMsFor(current));
    const clear = window.setTimeout(() => setCurrent(null), holdMsFor(current) + FADE_MS);
    return () => {
      window.clearTimeout(hold);
      window.clearTimeout(clear);
    };
  }, [current]);

  // Turning it off takes the mark down with it and forgets the queue.
  useEffect(() => {
    if (enabled) return;
    queue.current = [];
    setCurrent(null);
    setVisible(false);
  }, [enabled]);

  /*
   * Where to sit, and how far to reach.
   *
   * Measured rather than guessed: the mark is placed against the region's own box, on whichever
   * side has room, and the leader spans the gap between the two. Read in a layout effect and again
   * on scroll and resize, because the page moves under it while the run plays.
   */
  /*
   * Bring the region into view, but only when it is not already.
   *
   * The page is about three thousand pixels tall and the viewport is not, so a mark for the gate
   * ladder fired while the reader is at the top would otherwise point at something two thousand
   * pixels below the fold: a leader line to nothing. Scrolling is not scrubbing and does not touch
   * the cursor, the speed or the playing state, so the run carries on underneath it.
   *
   * A region already on screen is left alone, which is the common case once the reader has settled
   * on the part of the board they care about.
   */
  useEffect(() => {
    if (!current) return;
    const region = document.querySelector<HTMLElement>(`[data-anchor="${current.anchor}"]`);
    if (!region) return;
    const box = region.getBoundingClientRect();
    const margin = 80;
    const alreadyVisible = box.top >= margin && box.bottom <= window.innerHeight - margin;
    if (alreadyVisible) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    region.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  }, [current]);

  useLayoutEffect(() => {
    if (!current) return undefined;
    const place = () => {
      const region = document.querySelector<HTMLElement>(`[data-anchor="${current.anchor}"]`);
      const node = panel.current;
      if (!region || !node) return;
      const target = region.getBoundingClientRect();
      const own = node.getBoundingClientRect();
      const gap = 20;
      const margin = 12;

      // Vertically centred on the region, then pulled inside the viewport.
      let top = target.top + target.height / 2 - own.height / 2;
      top = Math.min(window.innerHeight - own.height - margin, Math.max(margin, top));

      // To the right of the region if it fits, otherwise inside its right edge.
      const roomRight = window.innerWidth - target.right;
      const toRight = roomRight > own.width + gap + margin;
      const left = toRight
        ? target.right + gap
        : Math.max(margin, target.right - own.width - gap);

      const leaderLeft = toRight ? target.right : left + own.width;
      const leaderWidth = toRight ? gap : Math.max(0, target.right - (left + own.width));
      setPlacement({
        top,
        left,
        leaderTop: top + own.height / 2,
        leaderLeft,
        leaderWidth,
      });
    };
    place();
    // The panel measures itself, so place once more after it has text in it, and keep placing
    // while a smooth scroll is still moving the region under it.
    const again = window.setTimeout(place, 0);
    const settle = window.setInterval(place, 100);
    const stop = window.setTimeout(() => window.clearInterval(settle), 900);
    window.addEventListener("scroll", place, { passive: true });
    window.addEventListener("resize", place);
    return () => {
      window.clearTimeout(again);
      window.clearInterval(settle);
      window.clearTimeout(stop);
      window.removeEventListener("scroll", place);
      window.removeEventListener("resize", place);
    };
  }, [current]);

  if (!enabled || !current) return null;

  return (
    <div className="rp-coach-layer" aria-live="polite">
      {placement && placement.leaderWidth > 0 && (
        <span
          aria-hidden="true"
          className={`rp-coach-leader${visible ? " is-on" : ""}`}
          style={{
            top: placement.leaderTop,
            left: placement.leaderLeft,
            width: placement.leaderWidth,
          }}
        />
      )}
      <div
        ref={panel}
        className={`rp-coach${visible ? " is-on" : ""}`}
        style={placement ? { top: placement.top, left: placement.left } : { opacity: 0 }}
      >
        <p className="rp-coach-label">{current.label}</p>
        <p className="rp-coach-text">{current.sentence}</p>
      </div>
    </div>
  );
}
