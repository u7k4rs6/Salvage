import { useEffect, useRef, useState } from "react";

/**
 * The character scramble decode.
 *
 * A value that changed state resolves by cycling random glyphs before settling, over 450ms with
 * an ease-out so most of the string lands early and the tail settles last. It is the only motion
 * on the page beyond a 150ms hover, and it is deliberately rationed: it fires when a value
 * *changes*, never on first paint, because a decode on load is decoration and a decode on change
 * is information. The four places it is allowed are the diagnosis cause reconciling, the
 * confidence landing, an incident id materialising, and a stat moving when the window advances.
 *
 * Glyphs are drawn from the same class as the character they stand in for, so a decoding number
 * stays a number and never flickers into letters. Anything that is not alphanumeric is held
 * still, which keeps separators, currency and punctuation in place while the value resolves and
 * stops the string changing width mid-flight.
 */

const DIGITS = "0123456789";
const LOWER = "abcdefghijklmnopqrstuvwxyz";
const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

const DURATION = 450;

function classOf(character: string): string | null {
  if (character >= "0" && character <= "9") return DIGITS;
  if (character >= "a" && character <= "z") return LOWER;
  if (character >= "A" && character <= "Z") return UPPER;
  return null;
}

function glyphFor(character: string): string {
  const pool = classOf(character);
  if (pool === null) return character;
  return pool[Math.floor(Math.random() * pool.length)];
}

/** Cubic ease-out. The settle front is fast, then slows into the final character. */
function easeOut(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export interface Scrambled {
  /** What to render. Equal to `value` except while a decode is running. */
  text: string;
  /** True while glyphs are still cycling, so the caller can mute the colour and hide it from AT. */
  running: boolean;
}

/**
 * `value` is rendered as given until it changes, then it decodes into the new value.
 *
 * `enabled` exists for the cases where a change is not a state change worth announcing. Passing
 * false renders the value directly and still records it, so the next real change decodes from
 * the right place rather than replaying everything that was skipped.
 */
export function useScramble(value: string, enabled = true): Scrambled {
  const [text, setText] = useState(value);
  const [running, setRunning] = useState(false);
  const previous = useRef(value);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (value === previous.current) return;
    previous.current = value;

    if (!enabled || prefersReducedMotion()) {
      setText(value);
      setRunning(false);
      return;
    }

    const characters = Array.from(value);
    const start = performance.now();
    setRunning(true);

    const step = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / DURATION, 1);
      // Everything left of the settle front is final; everything right of it is still cycling.
      const settled = Math.floor(easeOut(progress) * characters.length);

      setText(
        characters
          .map((character, index) => (index < settled ? character : glyphFor(character)))
          .join(""),
      );

      if (progress < 1) {
        frame.current = requestAnimationFrame(step);
        return;
      }
      setText(value);
      setRunning(false);
      frame.current = null;
    };

    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [value, enabled]);

  return { text, running };
}

/**
 * A decoding value, with the settled string kept in the accessibility tree.
 *
 * Mid-flight the glyphs are not the value, so they are hidden from assistive technology and the
 * real string is announced beside them. Without this a screen reader would read a slot machine.
 */
export function useScrambleProps(value: string, enabled = true) {
  const { text, running } = useScramble(value, enabled);
  return {
    text,
    running,
    /** Spread onto the element that renders `text`. */
    props: {
      "aria-hidden": running ? true : undefined,
      className: running ? "scrambling" : undefined,
    } as const,
    /** Render beside it when `running`, inside a visually hidden span. */
    announced: running ? value : null,
  };
}
