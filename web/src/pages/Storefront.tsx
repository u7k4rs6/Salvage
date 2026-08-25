import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream } from "../lib/useStream";
import { post } from "../lib/api";
import { Badge, Code, Empty, ErrorPanel, Panel, Region } from "../components/primitives";
import { rupees, timestamp } from "../lib/format";
import type { LedgerEntry } from "../lib/types";

interface Skus {
  skus: { sku: string; name: string; amount: number }[];
  key_id: string;
  available: boolean;
  reason: string;
}

interface CheckoutConfig {
  config: { display: Record<string, unknown> } | null;
  hint: {
    incident_id: string | null;
    segment_key: string | null;
    root_cause: string | null;
    hidden: string[];
    preferred: string[];
  } | null;
}

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

/** checkout.js is loaded only on this page, from Razorpay's domain (spec section 1). */
function useCheckoutScript(enabled: boolean) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    if (document.querySelector(`script[src="${CHECKOUT_SRC}"]`)) {
      setReady(true);
      return;
    }
    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => setReady(true);
    document.body.appendChild(script);
  }, [enabled]);
  return ready;
}

export default function StorefrontPage() {
  const { token } = useSession();
  const skus = useApi<Skus>("/api/storefront/skus");
  const hint = useApi<CheckoutConfig>("/api/storefront/checkout-config");
  const [paymentId, setPaymentId] = useState<string | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const ready = useCheckoutScript(skus.data?.available ?? false);

  // After a payment the page waits for the webhook rather than claiming success from the browser.
  // The browser learns the payment succeeded; the ledger learns it when Razorpay says so.
  useStream(["ledger.appended", "attempt"], () => {
    if (!orderId) return;
    fetch(`/api/ledger?ref_id=${encodeURIComponent(orderId)}&limit=20`)
      .then((response) => response.json())
      .then((body) => setEntries(body.entries ?? []))
      .catch(() => undefined);
  });

  async function buy(sku: string) {
    setBusy(true);
    setError(null);
    setPaymentId(null);
    try {
      const order = await post<any>("/api/storefront/order", { sku });
      setOrderId(order.order_id);
      const options: Record<string, unknown> = {
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.order_id,
        name: "Salvage demo store",
        description: sku,
        handler: (response: any) => setPaymentId(response.razorpay_payment_id),
        ...(order.checkout_config ?? {}),
      };
      const anyWindow = window as any;
      if (!anyWindow.Razorpay) {
        setError(new Error("checkout.js has not loaded yet"));
        return;
      }
      new anyWindow.Razorpay(options).open();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {hint.data?.hint && (
        <div className="border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span className="font-medium">
            {hint.data.hint.hidden.join(", ").toUpperCase()} is de-prioritised at checkout
          </span>{" "}
          because{" "}
          <span className="num">{(hint.data.hint.root_cause ?? "an incident").replace(/_/g, " ")}</span>{" "}
          is affecting <span className="num">{hint.data.hint.segment_key}</span>.
          {hint.data.hint.incident_id && (
            <>
              {" "}
              <Link
                to={`/incidents/${hint.data.hint.incident_id}`}
                className="text-accent underline hover:text-accent-hover"
              >
                See the incident
              </Link>
            </>
          )}
        </div>
      )}

      <Panel
        title="Demo store"
        subtitle="A real Razorpay test-mode Order and the real hosted checkout. Nothing here is simulated."
      >
        <Region state={skus} rows={2}>
          {(data) => (
            <>
              {!data.available && (
                <div className="mb-3 border border-neutral-300 bg-neutral-50 px-3 py-2 text-xs text-neutral-700">
                  {data.reason} Checkout is disabled rather than opened against a key that is not
                  there.
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-3">
                {data.skus.map((item) => (
                  <div key={item.sku} className="border border-neutral-300 p-3">
                    <div className="text-sm font-medium">{item.name}</div>
                    <div className="num mt-1 text-lg">{rupees(item.amount)}</div>
                    <button
                      type="button"
                      disabled={!data.available || busy || !ready}
                      onClick={() => buy(item.sku)}
                      className="mt-2 border border-accent bg-accent-soft px-3 py-1 text-xs text-accent-hover hover:bg-teal-100 disabled:opacity-50"
                    >
                      {busy ? "Working" : "Buy"}
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
        </Region>

        {error !== null && (
          <div className="mt-3">
            <ErrorPanel error={error} />
          </div>
        )}

        {hint.data?.config && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-accent hover:text-accent-hover">
              checkout config sent to Razorpay
            </summary>
            <Code>{JSON.stringify(hint.data.config, null, 2)}</Code>
          </details>
        )}
      </Panel>

      <Panel
        title="What happened"
        subtitle="The browser learns the payment result immediately. Salvage learns it when the webhook arrives, and that is what lands in the ledger."
      >
        {paymentId && (
          <div className="mb-3 text-sm">
            <Badge tone="green">payment</Badge>{" "}
            <span className="num">{paymentId}</span>
          </div>
        )}
        {orderId && (
          <div className="mb-3 text-sm">
            <Badge>order</Badge> <span className="num">{orderId}</span>
          </div>
        )}
        {entries.length === 0 ? (
          <Empty>
            {orderId
              ? "Waiting for the webhook. Nothing is written until Razorpay sends it."
              : "No order yet."}
          </Empty>
        ) : (
          <ul className="space-y-1">
            {entries.map((entry) => (
              <li key={entry.seq} className="num text-xs">
                <span className="text-neutral-500">{entry.seq}</span>{" "}
                <Badge>{entry.kind}</Badge>{" "}
                <span className="text-neutral-600">{timestamp(entry.ts)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Simulate a failure"
        subtitle="Dev only. Posts a synthetic failed attempt for the demo customer so the Overview reacts without a real failed payment."
      >
        <button
          type="button"
          disabled={!token}
          title={token ? undefined : "enter the token"}
          onClick={async () => {
            setError(null);
            try {
              await post("/api/storefront/simulate-failure", {}, token);
            } catch (cause) {
              setError(cause);
            }
          }}
          className="border border-red-400 bg-red-50 px-3 py-1 text-xs text-red-800 hover:bg-red-100 disabled:opacity-50"
        >
          {!token && <span aria-hidden="true">&#128274; </span>}
          Simulate my payment failing
        </button>
        <p className="mt-2 text-xs text-neutral-600">
          This writes one failed attempt. It does not fabricate a webhook, so nothing appears in
          the webhook ledger for it.
        </p>
      </Panel>
    </div>
  );
}
