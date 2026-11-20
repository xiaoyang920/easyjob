interface Aperture { x: number, y: number, fraction: number }
interface Point { x: number, y: number }

const SIZE = 256
const cache = new Map<string, Promise<Aperture | undefined>>()

/** Find the connected transparent area in the centre of a closed frame. */
export function pendantAperture(url: string) {
  const cached = cache.get(url)
  if (cached) return cached
  if (cache.size >= 64) cache.delete(cache.keys().next().value!)
  const aperture = measure(url).catch(() => undefined)
  cache.set(url, aperture)
  return aperture
}

async function measure(url: string): Promise<Aperture | undefined> {
  const image = new Image()
  image.src = url
  await image.decode()
  if (image.naturalWidth !== image.naturalHeight) return

  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = SIZE
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return
  ctx.drawImage(image, 0, 0, SIZE, SIZE)
  const pixels = ctx.getImageData(0, 0, SIZE, SIZE).data
  const centre = SIZE * (SIZE / 2) + SIZE / 2
  if (pixels[centre * 4 + 3]! >= 128) return

  const area = new Uint8Array(SIZE * SIZE)
  const queue = new Uint32Array(area.length)
  area[centre] = 1
  queue[0] = centre
  let length = 1
  for (let index = 0; index < length; index++) {
    const point = queue[index]!
    const x = point % SIZE
    const y = Math.floor(point / SIZE)
    // An open ornament uses the standard circular portrait.
    if (x <= 3 || y <= 3 || x >= SIZE - 4 || y >= SIZE - 4) return
    for (const next of [point - 1, point + 1, point - SIZE, point + SIZE]) {
      if (area[next] || pixels[next * 4 + 3]! >= 128) continue
      area[next] = 1
      queue[length++] = next
    }
  }
  if (length < area.length * .18 || length > area.length * .63) return

  const edge: Point[] = []
  for (let angle = 0; angle < 72; angle++) {
    const radians = angle * Math.PI / 36
    for (let radius = 1; radius < SIZE; radius++) {
      const x = Math.round(SIZE / 2 + Math.cos(radians) * radius)
      const y = Math.round(SIZE / 2 + Math.sin(radians) * radius)
      if (!area[y * SIZE + x]) {
        edge.push({ x, y })
        break
      }
    }
  }

  // Use the longest matching circular arc. Mascots which overlap the opening
  // contribute short, inward edges that must not shrink the fitted opening.
  let best: (Point & { radius: number, matches: number, error: number }) | undefined
  for (const [i, a] of edge.entries()) {
    if (i % 4) continue
    for (let j = i + 12; j < edge.length; j += 4) {
      for (let k = j + 12; k < edge.length; k += 4) {
        const circle = through(a, edge[j]!, edge[k]!)
        if (!circle || circle.radius < SIZE * .25 || circle.radius > SIZE * .44
            || Math.hypot(circle.x - SIZE / 2, circle.y - SIZE / 2) > SIZE * .11) continue
        let matches = 0, error = 0
        for (const point of edge) {
          const distance = Math.abs(Math.hypot(point.x - circle.x, point.y - circle.y) - circle.radius)
          if (distance <= 2) { matches++; error += distance }
        }
        if (!best || matches > best.matches || (matches === best.matches && error < best.error)) {
          best = { ...circle, matches, error }
        }
      }
    }
  }
  if (!best || best.matches < edge.length * .30) return
  return { x: best.x / SIZE, y: best.y / SIZE, fraction: (best.radius + 1) * 2 / SIZE }
}

function through(a: Point, b: Point, c: Point) {
  const bx = b.x - a.x, by = b.y - a.y, cx = c.x - a.x, cy = c.y - a.y
  const determinant = 2 * (bx * cy - by * cx)
  if (Math.abs(determinant) < 1) return
  const b2 = bx * bx + by * by, c2 = cx * cx + cy * cy
  const u = (cy * b2 - by * c2) / determinant
  const v = (bx * c2 - cx * b2) / determinant
  return { x: a.x + u, y: a.y + v, radius: Math.hypot(u, v) }
}
