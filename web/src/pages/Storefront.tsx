import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream } from "../lib/useStream";
import { post } from "../lib/api";
import { Badge, Code, Empty, ErrorPanel, Panel, Region } from "../components/primitives";
import { rupees, timestamp } from "../lib/format";
import type { LedgerEntry } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

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
      <PageIntro
        title="Storefront"
        what="What a shopper sees, so you can watch a real failure go in one end and come out the other end of the console."
        use="Buying needs Razorpay test keys in .env, and Simulate a failure needs the dashboard token in the top bar. Without either, the buttons stay disabled on purpose rather than pretending to work."
        shows={[
          ["Demo store", "three items at real prices. Buy opens Razorpay's own hosted test checkout, not a mock of it"],
          ["What happened", "the result the browser saw, then the webhook Salvage received. Those arrive at different times and the ledger records the second"],
          ["Simulate a failure", "writes one failed attempt for the demo customer so the rest of the console reacts, without needing a real card to decline"],
        ]}
        caveat="Test mode only. Startup refuses to run if the Razorpay key does not begin with rzp_test_, so no live key can be used here."
      />
      {hint.data?.hint && (
        <div className="border border-[color:var(--warn)] bg-[color:var(--warn-bg)] px-3 py-2 text-sm text-[color:var(--warn)]">
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
                className="text-[color:var(--info)] underline hover:text-[color:var(--fg)]"
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
              {/* This state reads as a broken page unless it says, at the size of a warning rather
                  than a footnote, that nothing is broken and exactly what is missing. */}
              {!data.available && (
                <div className="mb-4 border border-[color:var(--warn)] border-l-2 bg-[color:var(--warn-bg)] px-4 py-3">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.08em] text-[color:var(--warn)]">
                    Checkout is switched off, not broken
                  </div>
                  <p className="mt-1.5 text-[14px] leading-relaxed text-[color:var(--fg)]">
                    {data.reason} Checkout is disabled rather than opened against a key that is not
                    there, so the Buy buttons below do nothing on purpose.
                  </p>
                  <p className="mt-2 text-[13px] leading-relaxed text-[color:var(--fg-2)]">
                    To turn it on, put a Razorpay <span className="num">test</span> key pair in{" "}
                    <span className="num">.env</span> as{" "}
                    <span className="num">RAZORPAY_KEY_ID</span> and{" "}
                    <span className="num">RAZORPAY_KEY_SECRET</span>, then restart the API. Startup
                    refuses any key that does not begin with <span className="num">rzp_test_</span>,
                    so a live key cannot be used here. Everything else on this page, and every other
                    page, works without it.
                  </p>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-3">
                {data.skus.map((item) => (
                  <div key={item.sku} className="border border-[color:var(--line-2)] p-3">
                    <div className="text-sm font-medium">{item.name}</div>
                    <div className="num mt-1 text-lg">{rupees(item.amount)}</div>
                    <button
                      type="button"
                      disabled={!data.available || busy || !ready}
                      onClick={() => buy(item.sku)}
                      className="mt-2 border border-[color:var(--info)] bg-[color:var(--info-bg)] px-3 py-1 text-[13px] text-[color:var(--info)] hover:bg-[color:var(--info-bg)] disabled:opacity-50"
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
            <summary className="cursor-pointer text-[13px] text-[color:var(--info)] hover:text-[color:var(--fg)]">
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
              <li key={entry.seq} className="num text-[13px]">
                <span className="text-[color:var(--fg-3)]">{entry.seq}</span>{" "}
                <Badge>{entry.kind}</Badge>{" "}
                <span className="text-[color:var(--fg-2)]">{timestamp(entry.ts)}</span>
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
          className="border border-[color:var(--crit)] bg-[color:var(--crit-bg)] px-3 py-1 text-[13px] text-[color:var(--crit)] hover:bg-[color:var(--crit-bg)] disabled:opacity-50"
        >

          Simulate my payment failing
        </button>
        <p className="mt-2 text-[13px] text-[color:var(--fg-2)]">
          This writes one failed attempt. It does not fabricate a webhook, so nothing appears in
          the webhook ledger for it.
        </p>
      </Panel>
    </div>
  );
}
