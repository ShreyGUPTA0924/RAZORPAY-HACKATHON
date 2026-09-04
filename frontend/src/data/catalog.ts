import raw from './catalog-sample-raw.json'

// Real output from pipeline/extract.py's committed run (eval/extraction_results.json)
// against the real 60-SKU catalog, curated down to a representative 18 for
// the demo -- a mix of clean high-confidence rows and every real redaction
// pattern found in the actual run (model_compat, material, wattage_w).
// Nothing here is fabricated; see eval/extraction_results.json for the source.

export const ATTRIBUTE_FIELDS = [
  'accessory_type',
  'model_compat',
  'connector_type',
  'wattage_w',
  'capacity_mah',
  'screen_size_in',
  'wireless_charging',
  'material',
] as const

export type AttributeField = (typeof ATTRIBUTE_FIELDS)[number]

export interface AttrValue {
  value: string | number | boolean | string[] | null
  confidence: number
}

export interface CatalogRow {
  skuId: string
  title: string
  pricePaise: number
  published: boolean
  redactedFields: string[]
  attributes: Record<AttributeField, AttrValue>
}

export const catalogSample = raw as CatalogRow[]

export const FIELD_LABELS: Record<AttributeField, string> = {
  accessory_type: 'Accessory type',
  model_compat: 'Model compatibility',
  connector_type: 'Connector type',
  wattage_w: 'Wattage',
  capacity_mah: 'Capacity',
  screen_size_in: 'Screen size',
  wireless_charging: 'Wireless charging',
  material: 'Material',
}

export function formatPaise(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

export function formatAttrValue(field: AttributeField, attr: AttrValue): string {
  if (attr.value === null || attr.value === undefined) return '—'
  if (Array.isArray(attr.value)) {
    if (attr.value.length === 0) return 'Universal'
    return attr.value.map((v) => v.replace(/_/g, ' ')).join(', ')
  }
  if (typeof attr.value === 'boolean') return attr.value ? 'Yes' : 'No'
  if (field === 'wattage_w') return `${attr.value}W`
  if (field === 'capacity_mah') return `${attr.value} mAh`
  if (field === 'screen_size_in') return `${attr.value}"`
  return String(attr.value).replace(/_/g, ' ')
}
