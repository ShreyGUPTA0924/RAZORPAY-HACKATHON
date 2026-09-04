import { PackageSearch, Search } from 'lucide-react'
import * as React from 'react'
import { ProductCard } from '@/components/catalog/product-card'
import { Badge } from '@/components/ui/badge'
import { CATEGORIES, publishedCatalog } from '@/data/surface'
import { cn } from '@/lib/utils'

export function SurfaceView() {
  const [query, setQuery] = React.useState('')
  const [category, setCategory] = React.useState<string | null>(null)

  const filtered = publishedCatalog.filter((p) => {
    const matchesQuery = query.trim() === '' || p.title.toLowerCase().includes(query.trim().toLowerCase())
    const matchesCategory = category === null || p.category === category
    return matchesQuery && matchesCategory
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-heading text-foreground">Generated agent-commerce surface</h2>
        <p className="text-body-sm text-muted-foreground">
          Exactly what <code className="rounded bg-muted px-1.5 py-0.5 text-caption font-mono">search_catalog</code> /{' '}
          <code className="rounded bg-muted px-1.5 py-0.5 text-caption font-mono">get_product</code> return to a buyer
          agent — redacted low-confidence fields are gone, not shown-but-untrusted.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search products…"
            className="h-9 w-full rounded-md border border-input bg-card pl-9 pr-3 text-body-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setCategory(null)}
            className={cn(
              'rounded-full border px-3 py-1 text-caption font-medium capitalize transition-colors',
              category === null
                ? 'border-transparent bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:text-foreground'
            )}
          >
            All
          </button>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(c)}
              className={cn(
                'rounded-full border px-3 py-1 text-caption font-medium capitalize transition-colors',
                category === c
                  ? 'border-transparent bg-primary text-primary-foreground'
                  : 'border-border text-muted-foreground hover:text-foreground'
              )}
            >
              {c.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Badge variant="secondary">{filtered.length} of {publishedCatalog.length} SKUs</Badge>
        <Badge variant="success">100% published clean</Badge>
      </div>

      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 animate-fade-in">
          {filtered.map((product) => (
            <ProductCard key={product.skuId} product={product} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-center">
          <PackageSearch className="size-8 text-muted-foreground" />
          <p className="text-body-sm text-muted-foreground">No products match that search.</p>
        </div>
      )}
    </div>
  )
}
