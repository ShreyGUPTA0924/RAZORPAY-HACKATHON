/**
 * The ONLY place in the frontend that calls `fetch`. Every live-data screen
 * goes through here, never directly -- so the fallback-safe guarantee (any
 * backend failure -> cached fixture, never a broken UI) lives in one place.
 *
 * The cached-replay demo (Extraction / Surface / Agent mode / Results
 * screens) does not use this module at all and is unaffected by whether the
 * backend in api/ is running.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'
const HEALTH_TIMEOUT_MS = 2000
const DEFAULT_TIMEOUT_MS = 8000
// The two LLM-backed endpoints (injection-demo, extract/live) cap their own
// live attempt at 25s server-side before falling back to a cached result --
// give them room to return that cached result rather than timing out first.
const LLM_TIMEOUT_MS = 28000

async function fetchWithTimeout(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

export interface HealthStatus {
  reachable: boolean
  redisOk: boolean
}

export async function checkHealth(): Promise<HealthStatus> {
  try {
    const res = await fetchWithTimeout('/api/health', { method: 'GET' }, HEALTH_TIMEOUT_MS)
    if (!res.ok) return { reachable: false, redisOk: false }
    const json = await res.json()
    return { reachable: true, redisOk: Boolean(json.redis) }
  } catch {
    return { reachable: false, redisOk: false }
  }
}

export interface ApiResult<T> {
  data: T
  /** true if this value came from a cache/fixture somewhere -- either the
   * backend's own cached fallback, or this client's local fixture because
   * the backend couldn't be reached at all. */
  cached: boolean
  /** true only if this specific call actually reached the backend process
   * (whether or not the backend itself then returned a cached result). */
  live: boolean
}

async function postWithFallback<T>(path: string, body: unknown, fallback: T, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<ApiResult<T>> {
  try {
    const res = await fetchWithTimeout(
      path,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      },
      timeoutMs
    )
    if (!res.ok) throw new Error(`API ${path} responded ${res.status}`)
    const json = (await res.json()) as T
    const cached = typeof json === 'object' && json !== null && 'cached' in json ? Boolean((json as { cached: unknown }).cached) : false
    return { data: json, cached, live: true }
  } catch {
    return { data: fallback, cached: true, live: false }
  }
}

// ---- /api/refusals/{scenario} ----

export interface DecisionStep {
  label: string
  decision: string
  refusal_code: string | null
  refusal_detail: string | null
  cart_total: number | null
}

export interface ScenarioResult {
  scenario: string
  description: string
  steps: DecisionStep[]
}

export async function runRefusalScenario(scenario: string, fallback: ScenarioResult): Promise<ApiResult<ScenarioResult>> {
  return postWithFallback<ScenarioResult>(`/api/refusals/${scenario}`, undefined, fallback)
}

// ---- /api/extract/injection-demo ----

export interface InjectionDemoResult {
  cached: boolean
  title: string
  poisoned_description: string
  primary_value: string | null
  primary_confidence: number
  title_only_value: string | null
  title_only_confidence: number
  agreed: boolean | null
  final_confidence: number
  quarantined: boolean
  quarantine_reason: string | null
}

export async function runInjectionDemo(fallback: InjectionDemoResult): Promise<ApiResult<InjectionDemoResult>> {
  return postWithFallback<InjectionDemoResult>('/api/extract/injection-demo', undefined, fallback, LLM_TIMEOUT_MS)
}

// ---- /api/extract/live ----

export interface ExtractLiveField {
  field: string
  value: unknown
  confidence: number
}

export interface ExtractLiveResult {
  cached: boolean
  sku_id: string
  fields: ExtractLiveField[]
}

export async function runExtractLive(
  request: { sku_id: string; title: string; description: string },
  fallback: ExtractLiveResult
): Promise<ApiResult<ExtractLiveResult>> {
  return postWithFallback<ExtractLiveResult>('/api/extract/live', request, fallback, LLM_TIMEOUT_MS)
}
