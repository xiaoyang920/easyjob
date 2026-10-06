/** Shared home/profile card tilt; touch and reduced-motion users keep a stable card. */
export function updateCardTilt(card: HTMLElement, event: PointerEvent) {
  if (event.pointerType !== 'mouse' ||
      !window.matchMedia('(hover: hover) and (pointer: fine)').matches ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    resetCardTilt(card)
    return
  }
  const bounds = card.getBoundingClientRect()
  if (!bounds.width || !bounds.height) return
  const x = Math.max(-.5, Math.min(.5, (event.clientX - bounds.left) / bounds.width - .5))
  const y = Math.max(-.5, Math.min(.5, (event.clientY - bounds.top) / bounds.height - .5))
  card.style.setProperty('--tilt-x', `${y * -5}deg`)
  card.style.setProperty('--tilt-y', `${x * 5}deg`)
}

export function resetCardTilt(card: HTMLElement) {
  card.style.removeProperty('--tilt-x')
  card.style.removeProperty('--tilt-y')
}
