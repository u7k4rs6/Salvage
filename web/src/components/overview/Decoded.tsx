import { useScrambleProps } from "../../lib/useScramble";

/**
 * A value that decodes when it changes.
 *
 * The settled string is always what lands in the accessibility tree; the cycling glyphs are
 * hidden while they run. `enabled` is how a caller says "this change is not a state change":
 * passing false renders the value directly, which is what the stat row does on its first
 * window and what every value does under prefers-reduced-motion.
 */
export function Decoded({
  value,
  enabled = true,
  className = "",
  style,
}: {
  value: string;
  enabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}) {
  const { text, props, announced } = useScrambleProps(value, enabled);
  return (
    <>
      <span {...props} className={`${className} ${props.className ?? ""}`.trim()} style={style}>
        {text}
      </span>
      {announced !== null && <span className="sr-only">{announced}</span>}
    </>
  );
}
