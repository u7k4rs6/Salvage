/**
 * The expected segment keys, and the board model built by diffing them against a response.
 *
 * `GET /api/overview` cannot report a segment that is below the detector's floor. `_persist_stats`
 * in salvage/detect/run.py writes a `segments_stats` row only for windows where a key was live,
 * meaning at least 20 attempts, and `overview()` returns early when there is no row. So a
 * below-floor key is not a segment with `attempts: 0`. It is absent, and absent is
 * indistinguishable from "this instrument does not exist" unless the board holds the expected
 * list itself. That list is `segment_roster.json`, generated from salvage/sim/params.yaml.
 *
 * A key in the roster and missing from the response is below the detection floor, which is a
 * measurement fact worth showing, not a hole to hide.
 */
import rosterData from "./segment_roster.json";
import type { Segment } from "../lib/types";

export interface RosterNode {
  key: string;
  method: string;
  instrument: string;
  group: string;
  share_of_all_attempts: number;
  expected_attempts_mean_window: number;
  expected_attempts_peak_window: number;
  reaches_floor_at_peak: boolean;
  /** Within a quarter of the floor either side at peak, so it flips window to window. */
  marginal_at_peak: boolean;
}

export const ROSTER = rosterData.nodes as RosterNode[];
export const FLOOR_ATTEMPTS = rosterData._floor_attempts_per_window as number;
export const WALLET_NOTE = rosterData._wallet_has_no_instrument_dimension as string;

const BY_KEY = new Map(ROSTER.map((node) => [node.key, node]));

export const METHODS = ["upi", "card", "netbanking", "wallet"] as const;
export type Method = (typeof METHODS)[number];

/**
 * Dimension groups per method, in the order they are shown.
 *
 * `upi_nb_bank` is not a mistake. salvage/sim/traffic.py puts the UPI handle's bank into the
 * payment entity's `bank` field and the normalizer writes `bank` to the nb_bank column for every
 * method, so one UPI attempt produces both `upi:upi_handle:okhdfcbank` and `upi:nb_bank:HDFC`.
 * The two dimensions describe the same traffic twice and the labels have to say so, or a bank
 * name appears in the UPI row and reads as a netbanking bank.
 */
const GROUPS: Record<Method, { id: string; title: string; note?: string }[]> = {
  upi: [
    { id: "upi_handle", title: "handle" },
    {
      id: "upi_nb_bank",
      title: "handle bank",
      note: "the same UPI traffic keyed on the handle's bank, not netbanking",
    },
  ],
  card: [
    { id: "card_bin6", title: "BIN" },
    { id: "card_issuer", title: "issuer" },
    { id: "card_network", title: "network" },
  ],
  netbanking: [{ id: "nb_bank", title: "bank" }],
  wallet: [],
};

export type BoardNode =
  | {
      state: "measured";
      key: string;
      instrument: string;
      segment: Segment;
      roster: RosterNode | null;
    }
  | { state: "below_floor"; key: string; instrument: string; roster: RosterNode };

export interface BoardGroup {
  id: string;
  title: string;
  note?: string;
  nodes: BoardNode[];
  /** Set when the whole group is folded into one row instead of a grid of empty tiles. */
  collapsed: { label: string; detail: string; nodeCount: number } | null;
}

export interface BoardMethod {
  method: Method;
  methodNode: BoardNode | null;
  groups: BoardGroup[];
}

export interface Board {
  merchant: BoardNode | null;
  methods: BoardMethod[];
  measured: number;
  total: number;
}

/** `upi:upi_handle:okhdfcbank` to its three parts. Mirrors parse_key in detect/segments.py. */
export function parseKey(key: string): { method: string; dimension: string | null; value: string | null } {
  if (key === "all") return { method: "all", dimension: null, value: null };
  const parts = key.split(":");
  if (parts.length < 3) return { method: parts[0], dimension: null, value: null };
  return { method: parts[0], dimension: parts[1], value: parts.slice(2).join(":") };
}

/** The group id a key belongs to. UPI's nb_bank keys get their own id, see GROUPS above. */
function groupIdFor(key: string): string | null {
  const { method, dimension } = parseKey(key);
  if (dimension === null) return null;
  if (method === "upi" && dimension === "nb_bank") return "upi_nb_bank";
  if (dimension === "card_bin6") return "card_bin6";
  return dimension;
}

function measured(segment: Segment): BoardNode {
  return {
    state: "measured",
    key: segment.key,
    instrument: segment.instrument,
    segment,
    roster: BY_KEY.get(segment.key) ?? null,
  };
}

function belowFloor(node: RosterNode): BoardNode {
  return { state: "below_floor", key: node.key, instrument: node.instrument, roster: node };
}

/**
 * Diff a response against the roster.
 *
 * Two rules that matter more than they look:
 *
 * 1. A measured key is never dropped, even when it is not in the roster. The roster is generated
 *    from the simulator's instrument tables and a real merchant, or a changed params.yaml, will
 *    produce keys it does not know about. Those land in an "off roster" group rather than
 *    vanishing, because silently dropping measured data is the one failure this board cannot
 *    afford.
 * 2. A group is only collapsed while nothing in it is measured. A collapsed group that is hiding
 *    a live segment would be a lie about the current window, and the traffic level is a scenario
 *    parameter, so "never reaches the floor" is true of today's params.yaml and not of all of
 *    them.
 */
export function buildBoard(segments: Segment[]): Board {
  const byKey = new Map(segments.map((segment) => [segment.key, segment]));
  const merchantSegment = byKey.get("all");

  const methods: BoardMethod[] = METHODS.map((method) => {
    const methodSegment = byKey.get(method);
    const groups: BoardGroup[] = GROUPS[method].map(({ id, title, note }) => {
      const rosterNodes = ROSTER.filter((node) => node.group === id);
      const nodes: BoardNode[] = rosterNodes.map((node) => {
        const segment = byKey.get(node.key);
        return segment ? measured(segment) : belowFloor(node);
      });

      const anyMeasured = nodes.some((node) => node.state === "measured");
      const neverReachesFloor =
        rosterNodes.length > 0 && rosterNodes.every((node) => !node.reaches_floor_at_peak);

      return {
        id,
        title,
        note,
        nodes,
        collapsed:
          !anyMeasured && neverReachesFloor
            ? {
                label: "below detection floor at all hours",
                detail:
                  `All ${rosterNodes.length} exist as segment keys. The busiest sees about ` +
                  `${Math.round(Math.max(...rosterNodes.map((n) => n.expected_attempts_peak_window)))} ` +
                  `attempts in a peak 15-minute window against a floor of ${FLOOR_ATTEMPTS}.`,
                nodeCount: rosterNodes.length,
              }
            : null,
      };
    });

    // Wallet has no instrument dimension at all, which is a different claim from below floor:
    // `wallet` is not one of INSTRUMENT_DIMENSIONS in salvage/detect/segments.py, so a wallet
    // attempt only ever produces the `all` key and the `wallet` method key. There is nothing to
    // render at any volume, so the row states that rather than showing empty tiles.
    if (method === "wallet") {
      groups.push({
        id: "wallet_none",
        title: "instrument",
        nodes: [],
        collapsed: {
          label: "no instrument dimension",
          detail: WALLET_NOTE,
          nodeCount: 0,
        },
      });
    }

    // Anything measured that the roster does not know about.
    const known = new Set(groups.flatMap((group) => group.nodes.map((node) => node.key)));
    const offRoster = segments.filter((segment) => {
      const { method: segmentMethod, dimension } = parseKey(segment.key);
      return (
        segmentMethod === method &&
        dimension !== null &&
        !known.has(segment.key) &&
        groupIdFor(segment.key) !== null
      );
    });
    if (offRoster.length > 0) {
      groups.push({
        id: "off_roster",
        title: "off roster",
        note: "measured, but not an instrument this simulator's params.yaml produces",
        nodes: offRoster.map(measured),
        collapsed: null,
      });
    }

    return {
      method,
      methodNode: methodSegment
        ? measured(methodSegment)
        : (() => {
            const node = BY_KEY.get(method);
            return node ? belowFloor(node) : null;
          })(),
      groups,
    };
  });

  const total = ROSTER.length;
  const measuredCount = ROSTER.filter((node) => byKey.has(node.key)).length;

  return {
    merchant: merchantSegment
      ? measured(merchantSegment)
      : (() => {
          const node = BY_KEY.get("all");
          return node ? belowFloor(node) : null;
        })(),
    methods,
    measured: measuredCount,
    total,
  };
}
