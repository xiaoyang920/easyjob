import { shallowRef } from 'vue'
import { spaceIconsSlot, type SpaceArtwork } from './spaceSkins'

export const siteIconPack = shallowRef<SpaceArtwork>()

let owner = ''
let pending: object | undefined
let refreshAfter = 0

function signedInUser() {
  const id = localStorage.getItem('userId') || ''
  return localStorage.getItem('token') && /^[1-9]\d{0,18}$/.test(id) ? id : ''
}

export async function syncSiteIconPack() {
  const id = signedInUser()
  if (owner !== id) {
    owner = id
    siteIconPack.value = undefined
    pending = undefined
    refreshAfter = 0
  }
  if (!id || pending || Date.now() < refreshAfter) return

  const read = {}
  pending = read
  try {
    const response = await fetch('/api/user/space/' + id, {
      credentials: 'omit',
      cache: 'no-store',
      signal: AbortSignal.timeout(6000)
    })
    if (!response.ok) return
    const body = await response.json()
    if (pending === read && signedInUser() === id && body.code === 200 && body.data) {
      rememberSiteIconPack(id, body.data.equippedArtworks?.[spaceIconsSlot])
    }
  } catch {
    // Keep the current icons available when the profile cannot be loaded.
  } finally {
    if (pending === read) pending = undefined
  }
}

export function rememberSiteIconPack(userId: string | null, pack?: SpaceArtwork) {
  if (!userId || signedInUser() !== userId) return
  owner = userId
  pending = undefined
  siteIconPack.value = pack?.slot === spaceIconsSlot ? pack : undefined
  refreshAfter = Date.now() + 60_000
}
