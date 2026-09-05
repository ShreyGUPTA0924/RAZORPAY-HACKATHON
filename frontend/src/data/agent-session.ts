// A scripted buyer-agent session -- shaped exactly like the real
// surface/mandate.py + surface/gate.py + surface/mcp_server.py request/
// response payloads (see tests/test_e2e_buyer_agent.py's happy path,
// which this mirrors), not invented fields. Replayed client-side; no
// live MCP server or LLM call backs this demo.

export type StepActor = 'buyer' | 'mandate' | 'catalog' | 'gate' | 'payment'

export interface AgentStep {
  id: string
  actor: StepActor
  title: string
  narrative: string
  toolCall: string
  request: unknown
  response: unknown
  durationMs: number
}

const NOW = 1_772_000_000

export const agentSteps: AgentStep[] = [
  {
    id: 'intent',
    actor: 'buyer',
    title: 'Buyer agent presents Intent Mandate',
    narrative:
      'A scripted buyer agent holds its own Ed25519 keypair and signs an Intent Mandate authorizing up to ₹500 on chargers and cables.',
    toolCall: 'IntentMandate (self-signed by buyer)',
    request: null,
    response: {
      intent_mandate_id: 'intent-8f2c1a90',
      buyer_agent_id: 'scripted-agent-1',
      buyer_public_key_hex: '3f9a1c…e02b',
      max_amount: 50000,
      currency: 'INR',
      allowed_categories: ['charger', 'cable'],
      expiry: NOW + 3600,
      nonce: 'nonce-7d41',
      signature_hex: '9c7e2a…41f0',
    },
    durationMs: 900,
  },
  {
    id: 'verify',
    actor: 'mandate',
    title: 'verify_intent_mandate()',
    narrative: 'Signature checked against the claimed public key, expiry checked, nonce claimed atomically in Redis.',
    toolCall: 'surface.mandate.verify_intent_mandate',
    request: { intent_mandate_id: 'intent-8f2c1a90' },
    response: { valid: true, checks: ['signature_verified', 'not_expired', 'nonce_claimed'] },
    durationMs: 700,
  },
  {
    id: 'search',
    actor: 'catalog',
    title: 'search_catalog(category="charger")',
    narrative: 'Agent searches the generated MCP surface for a charger — only published, non-quarantined SKUs are visible.',
    toolCall: 'search_catalog',
    request: { category: 'charger' },
    response: [
      { sku_id: 'SKU-018', title: 'Newdort Usb Charger Full Charging Pad', price_paise: 29900 },
      { sku_id: 'SKU-047', title: 'Assvina 4 Port USB Fast Charger', price_paise: 59900 },
    ],
    durationMs: 850,
  },
  {
    id: 'get_product',
    actor: 'catalog',
    title: 'get_product("SKU-018")',
    narrative: 'Agent pulls full detail for the selected SKU before committing to a cart.',
    toolCall: 'get_product',
    request: { sku_id: 'SKU-018' },
    response: {
      sku_id: 'SKU-018',
      title: 'Newdort Usb Charger Full Charging Pad',
      category: 'charger',
      price_paise: 29900,
      attributes: { accessory_type: 'charger', connector_type: null, wattage_w: null },
    },
    durationMs: 700,
  },
  {
    id: 'gate',
    actor: 'gate',
    title: 'gate.evaluate() → ALLOW',
    narrative:
      'Deterministic checks run in order: mandate valid, cart non-empty, SKU published, category in scope, in stock, total under ceiling, under the cumulative running total for this mandate.',
    toolCall: 'surface.gate.evaluate',
    request: { requested_items: [{ sku_id: 'SKU-018', quantity: 1 }] },
    response: {
      decision: 'allow',
      cart_total: 29900,
      checks_passed: [
        'sku_published',
        'category_allowed',
        'in_stock',
        'under_price_ceiling',
        'under_cumulative_ceiling',
      ],
    },
    durationMs: 750,
  },
  {
    id: 'cart_mandate',
    actor: 'gate',
    title: 'issue_cart_mandate() — merchant-signed',
    narrative: 'Only reached on ALLOW. Binds the SKU + total to the verified intent, signed with the merchant key.',
    toolCall: 'create_cart_mandate',
    request: { intent_mandate_id: 'intent-8f2c1a90', requested_items: [{ sku_id: 'SKU-018', quantity: 1 }] },
    response: {
      cart_mandate_id: 'cart-intent-8f2c1a90-1772000004',
      total_amount: 29900,
      currency: 'INR',
      line_items: [{ sku_id: 'SKU-018', quantity: 1, unit_amount: 29900 }],
      signature_hex: '2b81fa…c390',
    },
    durationMs: 700,
  },
  {
    id: 'idempotency',
    actor: 'payment',
    title: 'idempotency.claim()',
    narrative: 'Atomic Redis claim on hash(intent_mandate_id + cart_hash) — only the caller that claims executes payment.',
    toolCall: 'surface.idempotency.claim',
    request: { intent_mandate_id: 'intent-8f2c1a90', cart_hash: 'a91f…' },
    response: { claimed: true, pending: false },
    durationMs: 500,
  },
  {
    id: 'payment',
    actor: 'payment',
    title: 'Razorpay order + capture (test mode)',
    narrative:
      'Real order/payment IDs from a human-completed Razorpay test-mode checkout, captured and reconciled against Razorpay\'s live API via this exact surface/payments.py code path. Amount is that real transaction\'s (₹1.00, netbanking) — a separate smoke test, not a live capture of this scripted cart\'s ₹299 total. See docs/what-broke.md.',
    toolCall: 'execute_payment_behind_gate',
    request: { razorpay_order_id: 'order_TYMYOQ0jzCVZLY', payment_id: 'pay_TYMYcCUNCJp6zY' },
    response: { status: 'captured', amount: 100, currency: 'INR', method: 'netbanking' },
    durationMs: 1100,
  },
]
