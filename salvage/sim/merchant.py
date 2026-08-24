"""Merchant fixture: the catalogue and the customer base.

Architecture section 9: about 20 SKUs (300 to 6,000 rupees), customers with a preferred
instrument, a secondary instrument for roughly 60 percent of them, a consent flag (about 70
percent true), a locale (about 40 percent hi_en), and a typical order value.

Every number comes from sim/params.yaml. Nothing here is a literal.

Synthetic contacts follow real formats (security doc section 5) so the redaction code is
exercised on realistic data. They never leave this module: only the salted ref_hash reaches the
database, so there is no raw contact anywhere in data/ for the simulated customers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from salvage.repo import ref_hash
from salvage.sim.params import Params
from salvage.sim.rng import Streams, pick, weighted_choice_table


@dataclass(frozen=True)
class Sku:
    sku_id: str
    name: str
    amount: int  # paise


@dataclass(frozen=True)
class Instrument:
    """One customer's way of paying. The fields that are set depend on the method."""

    method: str
    upi_handle: str | None = None
    upi_bank: str | None = None
    card_bin: str | None = None
    card_network: str | None = None
    card_issuer: str | None = None
    nb_bank: str | None = None
    wallet: str | None = None


@dataclass(frozen=True)
class SimCustomer:
    customer_id: str
    ref_hash: str
    consent: bool
    locale: str
    typical_amount: int
    preferred: Instrument
    alternate: Instrument | None

    def has_alternate_method(self) -> bool:
        return self.alternate is not None and self.alternate.method != self.preferred.method


_SKU_WORDS = (
    "Cotton Kurta",
    "Linen Shirt",
    "Steel Kettle",
    "Ceramic Mug",
    "Cane Basket",
    "Block Print Dupatta",
    "Jute Rug",
    "Copper Bottle",
    "Terracotta Planter",
    "Wool Throw",
    "Khadi Napkins",
    "Brass Diya Set",
    "Cotton Bedsheet",
    "Chanderi Stole",
    "Clay Cookware",
    "Bamboo Tray",
    "Handloom Towel",
    "Ikat Cushion",
    "Marble Coaster Set",
    "Leather Journal",
)


def build_catalogue(params: Params, streams: Streams) -> list[Sku]:
    """SKUs on a log-uniform price grid between the configured bounds."""
    merchant = params.merchant
    count = int(merchant["sku_count"])
    low, high = int(merchant["sku_min_paise"]), int(merchant["sku_max_paise"])
    rng = streams.customers
    prices = np.exp(rng.uniform(np.log(low), np.log(high), size=count))
    return [
        Sku(sku_id=f"sku_{i:03d}", name=_SKU_WORDS[i % len(_SKU_WORDS)], amount=int(round(price)))
        for i, price in enumerate(prices)
    ]


def _instrument_tables(params: Params) -> dict[str, Any]:
    traffic = params.traffic
    return {
        "method_names": list(traffic["method_mix"].keys()),
        "method_table": weighted_choice_table(list(traffic["method_mix"].values())),
        "upi": traffic["upi_handles"],
        "upi_table": weighted_choice_table([h["share"] for h in traffic["upi_handles"]]),
        "card": traffic["card_bins"],
        "card_table": weighted_choice_table([c["share"] for c in traffic["card_bins"]]),
        "nb": traffic["netbanking_banks"],
        "nb_table": weighted_choice_table([b["share"] for b in traffic["netbanking_banks"]]),
        "wallet": traffic["wallets"],
        "wallet_table": weighted_choice_table([w["share"] for w in traffic["wallets"]]),
    }


def _make_instrument(tables: dict[str, Any], method: str, draw: float) -> Instrument:
    if method == "upi":
        entry = tables["upi"][pick(tables["upi_table"], draw)]
        return Instrument(method="upi", upi_handle=entry["handle"], upi_bank=entry["bank"])
    if method == "card":
        entry = tables["card"][pick(tables["card_table"], draw)]
        return Instrument(
            method="card",
            card_bin=entry["bin6"],
            card_network=entry["network"],
            card_issuer=entry["issuer"],
        )
    if method == "netbanking":
        entry = tables["nb"][pick(tables["nb_table"], draw)]
        return Instrument(method="netbanking", nb_bank=entry["bank"])
    if method == "wallet":
        entry = tables["wallet"][pick(tables["wallet_table"], draw)]
        return Instrument(method="wallet", wallet=entry["wallet"])
    raise ValueError(f"unknown method {method!r}")


def synthetic_contact(index: int) -> str:
    """A synthetic Indian mobile number in real format. Never stored, never logged.

    Exists so that ref_hash is computed over something that looks like a real identifier, which is
    what the redaction tests need (security doc section 5).
    """
    return f"+9198{index % 100000000:08d}"


def build_customers(params: Params, streams: Streams) -> list[SimCustomer]:
    """The customer base. Drawn entirely from the 'customers' substream, so it is identical for
    every policy at the same seed."""
    merchant = params.merchant
    count = int(merchant["customer_count"])
    tables = _instrument_tables(params)
    rng = streams.customers

    method_draws = rng.random(count)
    instrument_draws = rng.random(count)
    consent_draws = rng.random(count)
    locale_draws = rng.random(count)
    secondary_draws = rng.random(count)
    alt_method_draws = rng.random(count)
    alt_instrument_draws = rng.random(count)
    typical = np.exp(
        rng.normal(
            float(merchant["typical_amount_lognormal_mu"]),
            float(merchant["typical_amount_lognormal_sigma"]),
            size=count,
        )
    )

    consent_rate = float(merchant["consent_rate"])
    hi_en_rate = float(merchant["locale_hi_en_rate"])
    secondary_rate = float(merchant["secondary_instrument_rate"])
    method_names = tables["method_names"]

    customers: list[SimCustomer] = []
    for i in range(count):
        method = method_names[pick(tables["method_table"], float(method_draws[i]))]
        preferred = _make_instrument(tables, method, float(instrument_draws[i]))

        alternate: Instrument | None = None
        if secondary_draws[i] < secondary_rate:
            # The alternate is drawn from the other methods, so it is genuinely an alternative
            # rail rather than a second card at the same issuer.
            others = [m for m in method_names if m != method]
            alt_method = others[int(alt_method_draws[i] * len(others)) % len(others)]
            alternate = _make_instrument(tables, alt_method, float(alt_instrument_draws[i]))

        customer_id = f"cust_{i:06d}"
        customers.append(
            SimCustomer(
                customer_id=customer_id,
                ref_hash=ref_hash(synthetic_contact(i)),
                consent=bool(consent_draws[i] < consent_rate),
                locale="hi_en" if locale_draws[i] < hi_en_rate else "en",
                typical_amount=int(round(float(typical[i]))),
                preferred=preferred,
                alternate=alternate,
            )
        )
    return customers


def customer_rows(customers: list[SimCustomer], created_at: int) -> list[dict[str, Any]]:
    """Rows for the customers table. No contact, no email, no name (security doc section 5)."""
    rows = []
    for customer in customers:
        preferred, alternate = customer.preferred, customer.alternate
        rows.append(
            {
                "id": customer.customer_id,
                "ref_hash": customer.ref_hash,
                "consent": int(customer.consent),
                "locale": customer.locale,
                "preferred_method": preferred.method,
                "upi_handle": preferred.upi_handle,
                "card_bin": preferred.card_bin,
                "card_network": preferred.card_network,
                "card_issuer": preferred.card_issuer,
                "nb_bank": preferred.nb_bank,
                "typical_amount": customer.typical_amount,
                "opted_out_at": None,
                "alt_method": alternate.method if alternate else None,
                "alt_upi_handle": alternate.upi_handle if alternate else None,
                "alt_card_bin": alternate.card_bin if alternate else None,
                "alt_nb_bank": alternate.nb_bank if alternate else None,
                "created_at": created_at,
            }
        )
    return rows
