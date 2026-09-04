import { Ban } from 'lucide-react'
import { ConfidenceBadge } from '@/components/extraction/confidence-badge'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ATTRIBUTE_FIELDS, type CatalogRow, FIELD_LABELS, formatAttrValue, formatPaise } from '@/data/catalog'
import { cn } from '@/lib/utils'

export function SkuRow({ row, revealed }: { row: CatalogRow; revealed: boolean }) {
  const populated = ATTRIBUTE_FIELDS.filter((f) => row.attributes[f].value !== null)
  const accessoryType = row.attributes.accessory_type

  return (
    <div
      className={cn(
        'group rounded-lg border px-4 py-3 transition-all duration-300',
        revealed ? 'animate-slide-up opacity-100' : 'pointer-events-none h-0 overflow-hidden border-0 p-0 opacity-0',
        row.published
          ? 'border-border bg-card hover:border-neutral-300 dark:hover:border-neutral-700'
          : 'border-danger/30 bg-danger-subtle/40'
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 text-caption font-mono text-muted-foreground">{row.skuId}</span>
          <span className="truncate text-body-sm font-medium text-foreground">{row.title}</span>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-body-sm tabular-nums text-muted-foreground">{formatPaise(row.pricePaise)}</span>
          {row.published ? (
            accessoryType.value && (
              <Badge variant="brand" className="capitalize">
                {String(accessoryType.value).replace(/_/g, ' ')}
              </Badge>
            )
          ) : (
            <Badge variant="danger">
              <Ban className="size-3" />
              Quarantined
            </Badge>
          )}
        </div>
      </div>

      {populated.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/60 pt-2.5">
          {populated.map((field) => (
            <Tooltip key={field}>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5">
                  <span className="text-caption text-muted-foreground">{FIELD_LABELS[field]}:</span>
                  <span className="text-caption font-medium text-foreground">
                    {formatAttrValue(field, row.attributes[field])}
                  </span>
                  <ConfidenceBadge attr={row.attributes[field]} redacted={row.redactedFields.includes(field)} />
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {FIELD_LABELS[field]} — {Math.round(row.attributes[field].confidence * 100)}% confidence
                {row.redactedFields.includes(field) && ' — redacted, below publish threshold'}
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
      )}
    </div>
  )
}
