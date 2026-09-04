import type { ScenarioResult } from '@/lib/api-client'

export type AttackIcon = 'ceiling' | 'cumulative' | 'expiry' | 'replay' | 'category' | 'retry' | 'signature'

export interface RefusalScenarioDef {
  id: string
  title: string
  narrative: string
  icon: AttackIcon
  /** A real, previously-captured response from this exact scenario (see the
   * curl verification in docs/what-broke.md's API section) -- used only if
   * the backend is unreachable when "Run attack" is clicked. Not invented. */
  cachedResult: ScenarioResult
}

export const refusalScenarios: RefusalScenarioDef[] = [
  {
    id: 'over_ceiling',
    title: 'Price ceiling bypass',
    narrative: "Buy something the mandate's price cap doesn't allow.",
    icon: 'ceiling',
    cachedResult: {
      scenario: 'over_ceiling',
      description: 'An agent tries to buy a ₹599 case against a ₹500 mandate ceiling.',
      steps: [
        {
          label: 'Purchase attempt',
          decision: 'refuse',
          refusal_code: 'over_price_ceiling',
          refusal_detail: 'cart total 59900 > ceiling 50000',
          cart_total: 59900,
        },
      ],
    },
  },
  {
    id: 'cumulative_ceiling',
    title: 'Cumulative spend bypass',
    narrative: 'Split one big purchase into two smaller ones to sneak under the cap.',
    icon: 'cumulative',
    cachedResult: {
      scenario: 'cumulative_ceiling',
      description:
        'One mandate, two transactions: ₹199 then ₹299 against a ₹450 ceiling -- neither alone is over, but together they are.',
      steps: [
        {
          label: 'First purchase (₹199 cable)',
          decision: 'allow',
          refusal_code: null,
          refusal_detail: null,
          cart_total: 19900,
        },
        {
          label: 'Second purchase (₹299 charger)',
          decision: 'refuse',
          refusal_code: 'cumulative_ceiling_exceeded',
          refusal_detail: 'cart total 29900 + already-spent 19900 = 49800 > ceiling 45000, even though this cart alone is under it',
          cart_total: 29900,
        },
      ],
    },
  },
  {
    id: 'expired_mandate',
    title: 'Expired mandate replay',
    narrative: 'Use an authorization after it should have expired.',
    icon: 'expiry',
    cachedResult: {
      scenario: 'expired_mandate',
      description: 'An agent presents a mandate that already expired before the transaction.',
      steps: [
        {
          label: 'Purchase attempt',
          decision: 'refuse',
          refusal_code: 'mandate_expired',
          refusal_detail: 'intent demo-13fc7913c4 expired at 1788551730, now 1788551740',
          cart_total: null,
        },
      ],
    },
  },
  {
    id: 'replayed_nonce',
    title: 'Nonce replay',
    narrative: 'Replay the exact same signed authorization a second time.',
    icon: 'replay',
    cachedResult: {
      scenario: 'replayed_nonce',
      description: 'An agent resubmits the exact same signed authorization a second time.',
      steps: [
        {
          label: 'First submission',
          decision: 'allow',
          refusal_code: null,
          refusal_detail: null,
          cart_total: 19900,
        },
        {
          label: 'Replayed submission',
          decision: 'refuse',
          refusal_code: 'nonce_replayed',
          refusal_detail: 'nonce nonce-16ab40fc19 already used for intent demo-54616a480d',
          cart_total: null,
        },
      ],
    },
  },
  {
    id: 'out_of_category',
    title: 'Category boundary violation',
    narrative: 'Buy something outside the categories the mandate allows.',
    icon: 'category',
    cachedResult: {
      scenario: 'out_of_category',
      description: "An agent's mandate only authorizes 'case' purchases; it tries to buy a charger.",
      steps: [
        {
          label: 'Purchase attempt',
          decision: 'refuse',
          refusal_code: 'category_not_allowed',
          refusal_detail: "SKU-018 category 'charger' not in allowed_categories ['case']",
          cart_total: null,
        },
      ],
    },
  },
  {
    id: 'retry_storm',
    title: 'Retry storm / double-charge',
    narrative: 'Retry the same payment repeatedly, hoping one slips through twice.',
    icon: 'retry',
    cachedResult: {
      scenario: 'retry_storm',
      description: 'An agent retries the same payment 5 times after never receiving a response -- only one may execute.',
      steps: [
        { label: 'Gate decision (checked once)', decision: 'allow', refusal_code: null, refusal_detail: null, cart_total: 19900 },
        { label: 'Retry attempt 1/5', decision: 'claimed', refusal_code: null, refusal_detail: null, cart_total: 19900 },
        {
          label: 'Retry attempt 2/5',
          decision: 'blocked',
          refusal_code: null,
          refusal_detail: 'Idempotency guard: same (intent, cart) already claimed',
          cart_total: null,
        },
        {
          label: 'Retry attempt 3/5',
          decision: 'blocked',
          refusal_code: null,
          refusal_detail: 'Idempotency guard: same (intent, cart) already claimed',
          cart_total: null,
        },
        {
          label: 'Retry attempt 4/5',
          decision: 'blocked',
          refusal_code: null,
          refusal_detail: 'Idempotency guard: same (intent, cart) already claimed',
          cart_total: null,
        },
        {
          label: 'Retry attempt 5/5',
          decision: 'blocked',
          refusal_code: null,
          refusal_detail: 'Idempotency guard: same (intent, cart) already claimed',
          cart_total: null,
        },
      ],
    },
  },
  {
    id: 'invalid_signature',
    title: 'Signature tampering',
    narrative: 'Alter a mandate’s terms after it was signed.',
    icon: 'signature',
    cachedResult: {
      scenario: 'invalid_signature',
      description: "An agent presents a mandate whose fields were altered after signing -- max_amount raised 10x post-signature.",
      steps: [
        {
          label: 'Purchase attempt',
          decision: 'refuse',
          refusal_code: 'invalid_signature',
          refusal_detail: 'signature does not verify for intent demo-ca9175f296',
          cart_total: null,
        },
      ],
    },
  },
]

/** Which real module + check produced each refusal code -- shown as
 * "caught by" under the hero refusal. */
export const CAUGHT_BY_CODE: Record<string, string> = {
  over_price_ceiling: 'surface/gate.py — price ceiling check',
  cumulative_ceiling_exceeded: 'surface/gate.py — cumulative spend guard',
  mandate_expired: 'surface/mandate.py — expiry check',
  nonce_replayed: 'surface/mandate.py — nonce replay check',
  category_not_allowed: 'surface/gate.py — category scope check',
  invalid_signature: 'surface/mandate.py — Ed25519 signature verification',
}

export const CAUGHT_BY_IDEMPOTENCY = 'surface/idempotency.py — claim guard'
