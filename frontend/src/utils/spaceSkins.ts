import decorationContract from '../../../contracts/decoration-slots.json'

/** Upload rule for one image position. The backend enforces the same contract. */
export interface DecorationImageRule {
  formats: string[]
  animated: boolean
  square: boolean
  minWidth: number
  maxWidth: number
  minHeight: number
  maxHeight: number
  maxKiB: number
  transparency: boolean
}

export interface DecorationSlot {
  label: string
  /** Only ready slots accept new artworks; a slot becomes ready once its renderer ships. */
  ready: boolean
  /** `wear`: one artwork per user; `collect`: every owned artwork is usable at once. */
  usage: 'wear' | 'collect'
  /** Guidance shown to designers in the admin upload form. */
  hint?: string
  layout?: Record<string, number>
  images: { key: string, label: string, rule: string }[]
  list?: { key: string, label: string, min: number, max: number, nameMaxLength: number, rule: string }
  settings: { key: string, label: string, type: 'slice' | 'color', image?: string, axis?: 'vertical' | 'horizontal' }[]
}

interface DecorationContract {
  rules: Record<string, DecorationImageRule>
  slots: Record<string, DecorationSlot>
}

const contract = decorationContract as DecorationContract
export const decorationRules = contract.rules
export const decorationSlots = contract.slots
export const readySlotKeys = Object.entries(decorationSlots).filter(([, slot]) => slot.ready).map(([key]) => key)

export function describeRule(rule: DecorationImageRule) {
  const size = rule.square ? `边长 ${rule.minWidth}–${rule.maxWidth} 像素的正方形`
    : `宽 ${rule.minWidth}–${rule.maxWidth}、高 ${rule.minHeight}–${rule.maxHeight} 像素`
  return `${rule.formats.join('/').toUpperCase()}${rule.animated ? '（可动图）' : '（静态）'}，${size}，最大 ${rule.maxKiB} KB`
    + (rule.transparency ? '，需要透明背景' : '')
}

/** Slot key shared with the backend (`SpaceArtwork.PENDANT`). */
export const avatarPendantSlot = 'avatarPendant'

export interface SpaceArtworkItem {
  key: string
  name: string
  url: string
}

/** A designer-made decoration. Its images and settings follow its slot in the decoration contract. */
export interface SpaceArtwork {
  artworkId: string
  slot: string
  name: string
  artist: string
  version: number
  assets: { images: Record<string, string>, items: SpaceArtworkItem[] }
  settings: Record<string, string | number>
}

/** A representative image for lists and shop cards: the first fixed image, else the first list item. */
export function artworkCover(artwork?: SpaceArtwork) {
  if (!artwork) return undefined
  const slot = decorationSlots[artwork.slot]
  const key = slot?.images[0]?.key
  return (key ? artwork.assets.images[key] : undefined) ?? artwork.assets.items[0]?.url
}

export function slotLabel(slot: string) {
  return decorationSlots[slot]?.label ?? slot
}

export function pendantImage(artwork?: SpaceArtwork) {
  return artwork?.slot === avatarPendantSlot ? artwork.assets.images.image : undefined
}

/** Slot keys shared with the backend constants in `SpaceArtwork`. */
export const chatBubbleSlot = 'chatBubble'
export const spaceIconsSlot = 'spaceIcons'
const bubbleScale = decorationSlots[chatBubbleSlot]?.layout?.displayScale
if (!bubbleScale) throw new Error('Decoration contract is missing the chat bubble display scale')

/**
 * CSS variables for the global `.decoration-bubble` class: a nine-slice image behind the text.
 * Received messages mirror the art horizontally, so their left and right paddings swap.
 * Returns undefined until every slice is a positive integer (for example while an admin is still typing).
 */
export function chatBubbleStyle(bubble: Pick<SpaceArtwork, 'assets' | 'settings'> | null | undefined, mirrored: boolean) {
  const image = bubble?.assets.images.image
  if (!bubble || !image) return undefined
  const [top, right, bottom, left] = ['sliceTop', 'sliceRight', 'sliceBottom', 'sliceLeft'].map(key => Number(bubble.settings[key]))
  if (![top, right, bottom, left].every(value => Number.isInteger(value) && value! > 0)) return undefined
  const px = (value: number) => value * bubbleScale! + 'px'
  const padding = (value: number) => px(Math.max(value, 16) + 4)
  return {
    '--bubble-flip': mirrored ? '-1' : '1',
    '--bubble-image': 'url(' + JSON.stringify(image) + ')',
    '--bubble-slice': `${top} ${right} ${bottom} ${left}`,
    '--bubble-width': `${px(top!)} ${px(right!)} ${px(bottom!)} ${px(left!)}`,
    '--bubble-padding-inline': `${padding(mirrored ? right! : left!)} ${padding(mirrored ? left! : right!)}`,
    '--bubble-min-height': px(top! + bottom! + 2),
    '--bubble-text': String(bubble.settings.textColor)
  }
}

export const spaceBannerRatios = ['16:9', '21:9', '3:2', '4:3'] as const

export interface SpaceBannerView {
  ratio: typeof spaceBannerRatios[number]
  x: number
  y: number
}

export function bannerView(view?: SpaceBannerView, position = 50): SpaceBannerView {
  return view ? { ...view } : { ratio: '16:9', x: 50, y: position }
}

export interface SpaceAppearance {
  spaceBannerUrl: string | null
  spaceBannerPosition: number
  spaceBannerView?: SpaceBannerView
  equippedArtworks: Record<string, SpaceArtwork>
}

/** A shop product. A standalone product sells exactly one artwork. */
export interface SpaceProduct {
  productId: string
  name: string
  coinPrice: number
  owned: boolean
  listed: boolean
  sortOrder: number
  version: number
  standaloneArtworkId: string | null
  artworks: Record<string, string>
}

/** The price this user pays; bundles are reduced by the share of artworks they already own. */
export interface SpaceQuote {
  price: number
  ownedArtworks: number
  totalArtworks: number
}

export interface SpaceCatalog {
  appearance: SpaceAppearance
  products: SpaceProduct[]
  balance: number
  artworks: SpaceArtwork[]
  ownedArtworks: string[]
  quotes: Record<string, SpaceQuote>
}

/** Artworks a product grants, in contract slot order. */
export function productArtworks(product: SpaceProduct, artworks: readonly SpaceArtwork[]) {
  return Object.keys(decorationSlots).flatMap(slot => {
    const id = product.artworks[slot]
    const artwork = id ? artworks.find(item => item.artworkId === id) : undefined
    return artwork ? [artwork] : []
  })
}

export interface AdminSpaceCatalog {
  products: SpaceProduct[]
  artworks: SpaceArtwork[]
}

export interface BannerReview {
  reviewId: string
  userId: string
  nickname: string
  state: 'PENDING' | 'APPROVED' | 'REJECTED'
  position: number
  view?: SpaceBannerView
  reason: string | null
  createdAt: string
}

/** Client-generated ids keep retried admin requests idempotent. */
export function spaceRequestId(kind: 'artwork' | 'product') {
  const bytes = crypto.getRandomValues(new Uint8Array(12))
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return kind === 'artwork' ? 'art:' + hex : 'product-' + hex
}

const pendantLayout = decorationSlots[avatarPendantSlot]?.layout
if (!pendantLayout?.canvas || !pendantLayout.avatarFraction) throw new Error('Decoration contract is missing the pendant layout')

/** Pendant canvas size and the share of it covered by the portrait. */
export const pendantGeometry = { canvas: pendantLayout.canvas, avatarFraction: pendantLayout.avatarFraction }

export function pendantTemplate() {
  const { canvas, avatarFraction } = pendantGeometry
  const center = canvas / 2
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${canvas}" height="${canvas}" viewBox="0 0 ${canvas} ${canvas}">
    <g id="alignment-guides-hide-before-export" fill="none" stroke="#52839a">
      <rect x=".5" y=".5" width="${canvas - 1}" height="${canvas - 1}"/>
      <circle cx="${center}" cy="${center}" r="${center * avatarFraction}"/>
      <path stroke-dasharray="4 4" d="M0 ${center}H${canvas} M${center} 0V${canvas}"/>
    </g></svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}
