// Respuestas de la API con la forma exacta del contrato (tipadas: si el backend cambia, esto no compila).
import type { Handoff, ScenariosResponse, SessionInfo, TurnResult } from "@/api/types";

export const scenarios: ScenariosResponse = {
  source: "demo_scenarios.json",
  disclaimer: "Sandbox con datos sintéticos · política sintética · no mueve dinero",
  data_source: "fixture",
  allow_any_customer: false,
  quick_replies: [
    { label: "sí", text: "sí" },
    { label: "la 1", text: "la 1" },
  ],
  scenarios: [
    {
      id: "normal_fixture",
      title: "Disputa normal con bloqueo",
      customer_id: "CLI-ANA",
      lang: "es",
      locale: "es-MX",
      category: "resolution",
      note: null,
      turns: [
        { kind: "message", text: "No reconozco un cargo de 77 dólares", expect_outcome: "clarify" },
        { kind: "message", text: "sí", expect_outcome: "resolved" },
      ],
      expected: { outcome: "resolved", rule: null },
    },
    {
      id: "high_amount_fixture",
      title: "Monto alto: handoff a analista (H02)",
      customer_id: "CLI-ANA",
      lang: "es",
      locale: "es-MX",
      category: "handoff",
      note: null,
      turns: [
        { kind: "message", text: "no reconozco el cargo de 1200 del 10/06/2026", expect_outcome: "handoff" },
      ],
      expected: { outcome: "handoff", rule: "H02_high_amount" },
    },
    {
      id: "fraud_pt",
      title: "Portugués: señal de fraude",
      customer_id: "CLI-ANA",
      lang: "pt",
      locale: "pt-BR",
      category: "handoff",
      note: null,
      turns: [{ kind: "message", text: "Não reconheço uma cobrança no Brasil", expect_outcome: "handoff" }],
      expected: { outcome: "handoff", rule: "H03_fraud_signal" },
    },
  ],
};

export const session: SessionInfo = { customer_id: "CLI-ANA", expires_in_s: 899, expired: false };

export const clarifyTurn: TurnResult = {
  conversation_id: "c_1",
  turn: 1,
  reply: "Encontré el cargo: 13/06/2026 · 77.00 USD. ¿Confirmas? (sí / no)",
  outcome: "clarify",
  lang: "es",
  awaiting: "confirmation",
  candidates: [],
  pending_action: { type: "open_dispute", card_label: "****1111" },
  understanding: { intent: "dispute_charge", confidence: 0.85, router: "rules", slots: { amount: 77 } },
  decision: {
    outcome: "auto_with_confirmation",
    policy_version: "2026-09-29.1",
    rules: [],
    facts: { customer_status: "Active", segment: "Basic" },
  },
  handoff: null,
  trace: [
    { node: "guard", next: "understand", ms: 1.2, detail: null, tools: [] },
    {
      node: "understand",
      next: "find_transaction",
      ms: 2.5,
      detail: "dispute_charge@0.85 router=rules",
      tools: [],
    },
    {
      node: "find_transaction",
      next: "decide",
      ms: 12.3,
      detail: "1 candidate",
      tools: [
        { tool: "search_transactions", ok: false, attempt: 1, error: "unavailable" },
        { tool: "search_transactions", ok: true, attempt: 2, ms: 4.1 },
      ],
    },
    { node: "decide", next: "respond", ms: 6, detail: "auto_with_confirmation rules=[]", tools: [] },
    { node: "respond", next: "fin", ms: 0.4, detail: null, tools: [] },
  ],
  trace_total_ms: 22.4,
};

export const handoffPacket: Handoff = {
  reason: "H02_high_amount",
  reason_text: "Monto alto: un analista debe revisar la disputa.",
  language: "es",
  created_at: "2026-06-17T10:00:00",
  request: ["no reconozco el cargo de 1200 del 10/06/2026"],
  verified_facts: {
    transaction: { transaction_id: "T-ANA-2", amount: 1200, currency: "USD" },
    customer_status: "Active",
  },
  policy: {
    version: "2026-09-29.1",
    rules_fired: [
      { id: "H02_high_amount", outcome: "handoff", explain: "Monto alto: un analista debe revisar." },
    ],
  },
  actions_taken: [],
  evidence: [{ turn: 1, node: "decide", tools: ["get_transaction", "get_profile"] }],
  unresolved_questions: ["Validar con el cliente si reconoce al comercio."],
  extra: { reference_id: "REF-123" },
};

export const handoffTurn: TurnResult = {
  ...clarifyTurn,
  reply: "Revisé el cargo. Ya le pasé tu caso a un asesor.",
  outcome: "handoff",
  awaiting: null,
  pending_action: null,
  decision: {
    outcome: "handoff",
    policy_version: "2026-09-29.1",
    rules: [{ id: "H02_high_amount", outcome: "handoff", explain: "Monto alto: un analista debe revisar." }],
    facts: {},
  },
  handoff: handoffPacket,
};
