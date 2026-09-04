import { Cable, Headphones, Layers, type LucideIcon, ShieldCheck, Smartphone, Zap } from 'lucide-react'
import { ATTRIBUTE_FIELDS, FIELD_LABELS, formatAttrValue, formatPaise } from '@/data/catalog'
import type { PublishedProduct } from '@/data/surface'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  cable: Cable,
  charger: Zap,
  headphone: Headphones,
  case: Layers,
  pouch: Layers,
}

export function ProductCard({ product }: { product: PublishedProduct }) {
  const Icon = CATEGORY_ICONS[product.category] ?? Layers
  const populated = ATTRIBUTE_FIELDS.filter((f) => product.attributes[f]?.value != null)
  const modelCompat = product.attributes.model_compat

  return (
    <Card className="flex flex-col transition-shadow hover:shadow-soft-md">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <Icon className="size-4.5" />
          </div>
          <div className="min-w-0">
            <p className="line-clamp-2 text-body-sm font-medium leading-snug text-foreground">{product.title}</p>
            <p className="mt-0.5 text-caption font-mono text-muted-foreground">{product.skuId}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 pt-0">
        <div className="flex items-center justify-between">
          <span className="text-heading-sm tabular-nums text-foreground">{formatPaise(product.pricePaise)}</span>
          <Badge variant="brand" className="capitalize">
            {product.category.replace(/_/g, ' ')}
          </Badge>
        </div>

        {modelCompat?.value !== undefined && modelCompat.value !== null && (
          <div className="flex items-start gap-1.5 rounded-md bg-success-subtle px-2.5 py-2 text-caption text-success">
            <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
            <span>
              {Array.isArray(modelCompat.value) && modelCompat.value.length === 0
                ? 'Verified compatible with all devices'
                : `Verified: ${formatAttrValue('model_compat', modelCompat)}`}
            </span>
          </div>
        )}

        <div className="mt-auto flex flex-wrap gap-1.5 border-t border-border/60 pt-3">
          {populated
            .filter((f) => f !== 'model_compat')
            .map((field) => (
              <Tooltip key={field}>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-caption text-muted-foreground">
                    {product.attributes[field] && formatAttrValue(field, product.attributes[field]!)}
                  </span>
                </TooltipTrigger>
                <TooltipContent>{FIELD_LABELS[field]}</TooltipContent>
              </Tooltip>
            ))}
          {populated.length === 0 && (
            <span className="inline-flex items-center gap-1 text-caption text-muted-foreground/70">
              <Smartphone className="size-3" />
              Category verified only
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
