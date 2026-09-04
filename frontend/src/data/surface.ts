import { type AttributeField, catalogSample, type CatalogRow } from './catalog'

// What a buyer agent actually sees through surface/mcp_server.py's tools --
// redacted fields are nulled out here exactly the way
// pipeline/quarantine.py's redact() does it in the real pipeline, and a
// quarantined SKU (none in this sample -- the real 60-SKU run had zero)
// would never appear at all. This is deliberately a SEPARATE derived view
// from the raw extraction data shown in the Extraction screen: that
// distinction -- "what the pipeline proposed" vs. "what's actually
// published" -- is the whole point of the quarantine gate.

export interface PublishedProduct {
  skuId: string
  title: string
  category: string
  pricePaise: number
  attributes: Partial<Record<AttributeField, CatalogRow['attributes'][AttributeField]>>
}

function toPublished(row: CatalogRow): PublishedProduct | null {
  if (!row.published) return null
  const attributes: PublishedProduct['attributes'] = {}
  for (const [field, attr] of Object.entries(row.attributes) as [AttributeField, CatalogRow['attributes'][AttributeField]][]) {
    attributes[field] = row.redactedFields.includes(field) ? { value: null, confidence: 0 } : attr
  }
  return {
    skuId: row.skuId,
    title: row.title,
    category: String(row.attributes.accessory_type.value ?? 'unknown'),
    pricePaise: row.pricePaise,
    attributes,
  }
}

export const publishedCatalog: PublishedProduct[] = catalogSample
  .map(toPublished)
  .filter((p): p is PublishedProduct => p !== null)

export const CATEGORIES = Array.from(new Set(publishedCatalog.map((p) => p.category))).sort()
