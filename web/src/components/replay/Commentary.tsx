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
/** Distance from the mark to the region it points at, and the leader's own length. */
const GAP = 16;
/** Keep the mark off the window edge. */
const MARGIN = 12;
/** Where the vertical leader meets the mark, measured from the mark's left edge. */
const LEADER_INSET = 22;

interface Leader {
  top: number;
  left: number;
  width: number;
  height: number;
}


/**
 * How much data a rectangle would cover.
 *
 * The sections on this page are full width, so a mark placed above or below its region always
 * lands on a neighbouring one. It does not have to land on the busy part of it: most sections
 * leave their right hand side empty, and the difference between the left edge and the right edge
 * is the difference between covering six rows of the ledger and covering nothing.
 *
 * Counts leaf elements that actually render text, which is the data, and ignores the layer itself.
 */
function dataCovered(rect: { top: number; left: number; right: number; bottom: number }): number {
  let hit = 0;
  const nodes = document.querySelectorAll("main *");
  for (const node of nodes) {
    if (!(node instanceof HTMLElement)) continue;
    if (node.children.length) continue;
    if (!node.textContent || !node.textContent.trim()) continue;
    if (node.closest(".rp-coach-layer")) continue;
    const box = node.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    // Only things sharing the mark's band are worth measuring.
    if (box.bottom <= rect.top || box.top >= rect.bottom) continue;
    if (box.right <= rect.left || box.left >= rect.right) continue;
    hit += 1;
  }
  return hit;
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
  const queue = useRef<Mark[]>([]);
  const shown = useRef<Set<number>>(new Set());
  const lastOrd = useRef(ord);
  const panel = useRef<HTMLDivElement | null>(null);
  const leader = useRef<HTMLSpanElement | null>(null);
  /** Whether the frame loop last found a position clear of the region. */
  const clearRef = useRef(false);

  // Collect the beats the head has just crossed. Reading the span between the last cursor and this
  // one catches a jump as well as a step, so scrubbing does not silently skip the commentary for
  // everything it passed over.
  // A new mark starts hidden and fades in once the frame loop has found it somewhere clear.
  useEffect(() => {
    setVisible(false);
    clearRef.current = false;
  }, [current]);

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

  /*
   * Hold, then fade, then release the slot.
   *
   * The clock starts when the mark is actually on screen rather than when it was queued: one that
   * waits for a scroll to land still gets its full reading time. Until the placement is clear of
   * the region, the mark is placed but not shown.
   */
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    if (!current) return;
    const poll = window.setInterval(() => {
      if (clearRef.current) setSettled(true);
    }, 60);
    return () => window.clearInterval(poll);
  }, [current]);

  useEffect(() => {
    if (!current || !settled) return;
    setVisible(true);
    const ms = holdMsFor(current);
    const hold = window.setTimeout(() => setVisible(false), ms);
    const done = window.setTimeout(() => setCurrent(null), ms + FADE_MS);
    return () => {
      window.clearTimeout(hold);
      window.clearTimeout(done);
    };
  }, [current, settled]);

  /*
   * A mark whose region never yields a clear position is dropped rather than shown over the data.
   * Nothing here has hit this on the recording, but a narrower window or a taller region could.
   */
  useEffect(() => {
    if (!current || settled) return;
    const giveUp = window.setTimeout(() => setCurrent(null), 2500);
    return () => window.clearTimeout(giveUp);
  }, [current, settled]);

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
   * Reserve a band for the mark, then bring the region into it.
   *
   * The regions here are full width sections, 1350px of a 1600px viewport, so there is never room
   * beside one: the mark has to go above or below. Some of them are also taller than the viewport,
   * the gate ladder is 1008px against 900, so centring the region leaves no band at all.
   *
   * So the scroll reserves the band rather than centring: the region's top is placed far enough
   * down that the mark and its leader fit above it, or, for a region short enough to sit fully on
   * screen with room underneath, it is left where a normal centring would put it. Scrolling is not
   * scrubbing and does not touch the cursor, the speed or the playing state.
   */
  useEffect(() => {
    if (!current) return;
    const region = document.querySelector<HTMLElement>(`[data-anchor="${current.anchor}"]`);
    const node = panel.current;
    if (!region) return;
    const markHeight = node?.getBoundingClientRect().height || 120;
    const band = markHeight + GAP + MARGIN;
    const box = region.getBoundingClientRect();

    // Already sitting with a clear band above it, and its top on screen: leave the page alone.
    if (box.top >= band && box.top < window.innerHeight) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollBy({ top: box.top - band, behavior: reduced ? "auto" : "smooth" });
  }, [current]);

  /*
   * Where to sit, and how far to reach.
   *
   * Never over the region it points at. Beside it if the viewport has the width, which on a full
   * width section it does not, then below it, then above it. The leader does the pointing, so the
   * mark has no reason to overlap and does not.
   */
  useLayoutEffect(() => {
    if (!current) return undefined;
    const place = () => {
      const region = document.querySelector<HTMLElement>(`[data-anchor="${current.anchor}"]`);
      const node = panel.current;
      const line = leader.current;
      if (!region || !node) return;
      const box = region.getBoundingClientRect();
      const own = node.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const top = Math.max(0, box.top);
      const bottom = Math.min(vh, box.bottom);
      const clampX = (x: number) => Math.min(vw - own.width - MARGIN, Math.max(MARGIN, x));
      const clampY = (y: number) => Math.min(vh - own.height - MARGIN, Math.max(MARGIN, y));

      let at: { top: number; left: number; line: Leader | null } | null = null;

      if (box.right + GAP + own.width + MARGIN <= vw) {
        const y = clampY(top + (bottom - top) / 2 - own.height / 2);
        at = { top: y, left: box.right + GAP,
          line: { top: y + own.height / 2, left: box.right, width: GAP, height: 1 } };
      } else if (box.left - GAP - own.width - MARGIN >= 0) {
        const y = clampY(top + (bottom - top) / 2 - own.height / 2);
        const x = box.left - GAP - own.width;
        at = { top: y, left: x,
          line: { top: y + own.height / 2, left: x + own.width, width: GAP, height: 1 } };
      } else {
        // Above or below, at whichever horizontal position covers least.
        const bestX = (bandTop: number) => {
          const options = [box.left, box.right - own.width,
            box.left + (box.right - box.left - own.width) / 2];
          let choice = clampX(options[0]);
          let fewest = Infinity;
          for (const option of options) {
            const left = clampX(option);
            const covered = dataCovered({ top: bandTop, left,
              right: left + own.width, bottom: bandTop + own.height });
            if (covered < fewest) { fewest = covered; choice = left; }
          }
          return choice;
        };
        if (bottom + GAP + own.height + MARGIN <= vh) {
          const y = bottom + GAP;
          const x = bestX(y);
          at = { top: y, left: x, line: { top: bottom, left: x + LEADER_INSET, width: 1, height: GAP } };
        } else if (top - GAP - own.height >= MARGIN) {
          const y = top - GAP - own.height;
          const x = bestX(y);
          at = { top: y, left: x,
            line: { top: y + own.height, left: x + LEADER_INSET, width: 1, height: GAP } };
        } else {
          // Taller than the window. Push it down until a band exists rather than sit on it.
          const wanted = own.height + GAP + MARGIN;
          if (box.top < wanted) {
            const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            window.scrollBy({ top: box.top - wanted, behavior: reduced ? "auto" : "smooth" });
          }
          at = { top: MARGIN, left: clampX(box.left), line: null };
        }
      }

      /*
       * Written to the node rather than to state, and the clearance measured from the position
       * just written.
       *
       * React commits a render asynchronously, so a mark told to hide could still paint for a
       * frame or two in the position it was told to leave. The board reflows constantly while the
       * run plays, rows landing in the ledger and counters growing, so those frames were real and
       * measurable. Writing here means the class and the geometry change in the same frame that
       * measured them, and there is no paint in between.
       */
      node.style.top = `${at.top}px`;
      node.style.left = `${at.left}px`;
      const clear =
        at.left >= box.right - 1 ||
        at.left + own.width <= box.left + 1 ||
        at.top >= box.bottom - 1 ||
        at.top + own.height <= box.top + 1;
      node.classList.toggle("is-clear", clear);
      clearRef.current = clear;

      if (line) {
        if (at.line && clear) {
          line.style.top = `${at.line.top}px`;
          line.style.left = `${at.line.left}px`;
          line.style.width = `${at.line.width}px`;
          line.style.height = `${at.line.height}px`;
          line.classList.add("is-clear");
        } else {
          line.classList.remove("is-clear");
        }
      }
    };

    let frame = 0;
    const loop = () => {
      place();
      frame = window.requestAnimationFrame(loop);
    };
    frame = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(frame);
  }, [current]);

  if (!enabled || !current) return null;

  return (
    <div className="rp-coach-layer" aria-live="polite">
      <span ref={leader} aria-hidden="true" className={`rp-coach-leader${visible ? " is-on" : ""}`} />
      <div ref={panel} className={`rp-coach${visible ? " is-on" : ""}`}>
        <p className="rp-coach-label">{current.label}</p>
        <p className="rp-coach-text">{current.sentence}</p>
      </div>
    </div>
  );
}
