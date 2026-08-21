/** A specimen at full size. The evidence behind a determination is too small to
 *  read in a 3:4 card, so every thumbnail in the app opens one of these. */
export function Lightbox({
  src,
  alt,
  caption,
  onClose,
}: {
  src: string
  alt: string
  caption: string
  onClose: () => void
}) {
  return (
    <div
      className="dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      tabIndex={-1}
      autoFocus
      onClick={onClose}
    >
      <figure className="lightbox">
        <img src={src} alt={alt} />
        <figcaption className="mono">{caption}</figcaption>
      </figure>
    </div>
  )
}
