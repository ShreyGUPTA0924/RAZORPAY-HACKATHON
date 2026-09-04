export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M16 7L23 24H19.2L17.6 20H14.4L12.8 24H9L16 7ZM16 12.8L14.9 16.6H17.1L16 12.8Z"
        className="fill-primary-foreground"
      />
    </svg>
  )
}
