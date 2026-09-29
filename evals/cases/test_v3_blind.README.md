# test_v3_blind — held-out conversations written blind

- File: `test_v3_blind.jsonl` (80 cases, one JSON object per line, UTF-8)
- sha256: `cec03e517347e3143d25b44fe7f1bf75b103669a44ba5869983865f23c52d20d`
- Author tag: `blind-v3`
- Policy used: `config/policy.yaml` version `2026-09-29.3`, `as_of` 2026-06-17

## Independence statement
The author read only these sources:
- `config/policy.yaml`
- the task prompt, which contained the product-behavior spec and the outcome vocabulary
- read-only SQL on `data/serving.duckdb`, opened with `read_only=True`. Tables used: customers, products, transactions, complaints.

The author did **not** open anything in `src/`, `tests/`, `evals/` (other than writing these two files), `scripts/`, `corpus/`, `docs/`, `reports/` or the README. The author did not look at any lexicon or existing test case, did not run the agent and did not use git. The only look inside `evals/cases/` was a filename check, to make sure no `v3` file already existed. Every message was written from the spec.

## Label procedure
1. SQL candidate pools, with ages computed as `as_of − date(transaction_date)`. Margins keep each case clear of the policy boundaries:
   - Resolvable: customer `Active` with **no rows in complaints**; txn `Approved`; age 8–100 days; amount < 70% of `high_amount[currency]`; `fraud_score` null or < 25; `Purchase` on an `Active` card. The merchant is unique for that customer within the last 160 days, so naming the merchant identifies the charge.
   - H01: customer `Inactive`, otherwise clean.
   - H02: `Transfer` on an account with amount ≥ 1.2 × threshold. No `Purchase` in the data reaches a threshold (max USD 500, COP 2M, ARS 175k).
   - H03: `fraud_score` ≥ 35.
   - H04: customer has an `is_repeat_complainer=True` complaint created on or after 2026-05-01.
   - D02/D03/D04: status Declined/Reversed/Pending.
   - D05: Approved, 180–250 days old.
   - In each H case the earlier rules were checked not to fire.
2. Ambiguity cases: SQL confirmed that ≥ 2 of the customer's transactions match what the user says (same merchant, or "como 300 dólares" / "430 y tantos" / "casi 60 lucas"). All candidates are clean, so the case tests disambiguation, not policy. Two cases are vague openers, and one case is a customer with 2 active cards asking to "block my card".
3. Turn labels:
   - Once the agent identifies an eligible charge it must ask for consent, so that turn is labeled `clarify` / `none`.
   - The consent turn is labeled `resolved` with `dispute`, `block` or `both`, following exactly what the customer authorizes (separate consent per action).
   - A policy handoff or rejection is labeled on the turn where the charge is identified.
4. A validator script checked the data behind the labels (after writing, independently of the agent):
   - It re-queried every `TRX-…` id cited in `rationale` and confirmed it belongs to the case's customer.
   - It re-applied the rule order from policy.yaml (D02→D03→D04→D05→H01→H02→H03→H04) and confirmed the labeled rule matches. Every resolvable case's transactions are rule-free.
   - It confirmed that every `block`/`both` case has an Active card.
   - Result: 0 mismatches.

## Mix
| category | n | % |
|---|---|---|
| normal (resolvable) | 28 | 35% |
| ambiguous / clarification | 16 | 20% |
| handoff | 20 | 25% |
| rejection (D-rule) | 8 | 10% |
| other (out-of-scope, closing, cancel, manipulation, clarification exhausted, D01) | 8 | 10% |

| dialect | n |
|---|---|
| es-MX | 31 |
| es-CO | 17 |
| es-AR (voseo) | 13 |
| pt-BR | 19 |

Handoff reasons:
- H02 ×5
- H03 ×5
- H01 ×3
- H04 ×3
- account_takeover ×2
- customer_request ×1
- consent_unclear ×1
- out_of_scope ×2 (in "other")
- clarification_exhausted ×1 (in "other")

Rejections: D02 ×2, D03 ×2, D04 ×2, D05 ×2. D01 ×1 (in "other", outcome `informed`).

## Known uncertainties
- **Consent-ask turn labeled `clarify`.** When the agent identifies the charge and asks "¿confirmas?", that turn is labeled `clarify`. A harness that reserves `clarify` for "which charge?" questions may label it differently.
- **Turn of `clarification_exhausted`** (the es-CO case with only vague messages). The label assumes 3 clarifications are allowed and the handoff comes on the 4th unproductive message. If the implementation hands off on the 3rd, the last `clarify` turn would be `handoff`.
- **D01 case (pt-BR, last case).** `txn_already_disputed` is assumed to include a dispute opened earlier in the same conversation, since the DB has no dispute table that links to a transaction. It is labeled `informed` / `D01_already_disputed`.
- **H02 cases use account `Transfer` debits.** No card purchase reaches the thresholds. Phrasing avoids "someone accessed my account" so these are not mistaken for takeover. An agent might still ask a clarifying question first.
- **Cloned-card case (pt-BR, `CLI-7TOVA7T1LELY`).** It is labeled `account_takeover` per the spec. An implementation could instead open a dispute or block the card.
- **Relative dates** assume the agent's "today" is `as_of` = 2026-06-17 (a Wednesday). Every such case also names the merchant, which is unique for that customer, so identification does not depend on the date.
- **pt-BR speakers use real MX/AR customers.** The DB has no Brazil customers, so their amounts are USD.
- **Timezone.** `transaction_date` looks like UTC (process_date is sometimes one day earlier). Ages were kept well away from the 120-day limit, so this does not affect any label.
- **Repeat complainer.** It is read as any complaint row with `is_repeat_complainer=True`. The H04 customers have such a row within the last 50 days, so a "last 90 days" reading gives the same label. Non-H04 cases use customers with no complaints at all.
