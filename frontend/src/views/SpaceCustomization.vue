<template>
  <main class="space-customization">
    <header class="customization-heading">
      <RouterLink to="/user-space">我的空间</RouterLink>
      <h1>空间装扮</h1>
    </header>
    <ContentState v-if="loading" kind="loading" title="正在加载空间装扮" />
    <ContentState v-else-if="loadError" kind="error" title="空间装扮暂时无法加载" :description="loadError" @retry="load" />
    <div v-else-if="catalog" class="customization-layout">
      <section class="customization-preview" aria-label="空间预览">
        <div class="preview-card">
          <SpaceBanner :url="previewUrl" v-model:position="framing.y" v-model:x="framing.x"
            :ratio="framing.ratio" :editable="!busy" />
          <div class="preview-profile">
            <SpaceAvatar class="preview-avatar" :src="profile?.avatar" :name="profile?.nickName"
              :pendant-url="pendantImage(previewArtwork(avatarPendantSlot))" />
            <h2>{{ profile?.nickName || '我的空间' }}</h2>
            <p v-if="profile?.personIntroduction">{{ profile.personIntroduction }}</p>
          </div>
        </div>
        <div v-if="previewUrl" class="position-row">
          <label for="space-banner-ratio">头图比例</label>
          <select id="space-banner-ratio" v-model="framing.ratio" :disabled="!!busy">
            <option v-for="ratio in spaceBannerRatios" :key="ratio" :value="ratio">{{ ratio }}</option>
          </select>
          <label for="space-banner-x">头图横向位置</label>
          <input id="space-banner-x" v-model.number="framing.x" type="range" min="0" max="100" :disabled="!!busy">
          <label for="space-banner-position">头图纵向位置</label>
          <input id="space-banner-position" v-model.number="framing.y" type="range" min="0" max="100" :disabled="!!busy">
          <button type="button" :disabled="!!busy || !framingChanged" @click="savePosition">保存位置</button>
        </div>
        <BubblePreview v-if="wearableSlots.includes(chatBubbleSlot)" class="preview-bubbles" :bubble="previewArtwork(chatBubbleSlot)" />
        <div v-if="wearableSlots.includes(spaceIconsSlot)" class="preview-icons" aria-label="图标包预览">
          <span v-for="icon in decorationSlots[spaceIconsSlot]?.images" :key="icon.key" class="preview-icon">
            <SpaceIcon :pack="previewArtwork(spaceIconsSlot)" :name="icon.key"><span class="icon-default" aria-hidden="true">·</span></SpaceIcon>
            {{ icon.label }}
          </span>
        </div>
      </section>
      <aside class="customization-options">
        <section v-for="slot in wearableSlots" :key="slot">
          <h2>{{ slotLabel(slot) }}</h2>
          <ContentState v-if="!owned(slot).length" kind="empty" :title="'还没有' + slotLabel(slot)"
            description="在装扮商城获得后，可以在这里使用。" />
          <div v-else class="artwork-options" role="group" :aria-label="'选择要使用的' + slotLabel(slot)">
            <button type="button" :aria-pressed="!previewIds[slot]" :disabled="!!busy" @click="previewIds[slot] = ''">
              <span class="artwork-thumb empty" aria-hidden="true"></span>
              <span>不使用</span>
            </button>
            <button v-for="art in owned(slot)" :key="art.artworkId" type="button"
              :aria-pressed="previewIds[slot] === art.artworkId" :disabled="!!busy" @click="previewIds[slot] = art.artworkId">
              <img class="artwork-thumb" :src="artworkCover(art)" alt="">
              <span>{{ art.name }}</span>
              <small>{{ artworkLabel(art) }}</small>
            </button>
          </div>
          <div class="slot-actions">
            <button v-if="previewIds[slot] && wornId(slot) !== previewIds[slot]" class="customization-action" type="button"
              :disabled="!!busy" @click="wear(slot, previewIds[slot] ?? '')">
              使用
            </button>
            <button v-if="wornId(slot)" class="remove-artwork" type="button" :disabled="!!busy" @click="wear(slot, '')">取消使用</button>
            <RouterLink class="shop-link" :to="shopLink(slot)">
              浏览{{ slotLabel(slot) }} <ArrowRight aria-hidden="true" />
            </RouterLink>
          </div>
        </section>
        <section v-for="slot in collectedSlots" :key="slot">
          <h2>我的{{ slotLabel(slot) }}</h2>
          <ContentState v-if="!owned(slot).length" kind="empty" :title="'还没有' + slotLabel(slot)"
            :description="'在硬币商城获得后，可以在私信里直接使用。'" />
          <article v-for="art in owned(slot)" :key="art.artworkId" class="collection-row">
            <img class="artwork-thumb" :src="artworkCover(art)" alt="">
            <div><strong>{{ art.name }}</strong><small>{{ art.assets.items.length }} 张 · {{ art.artist }}</small></div>
          </article>
          <div class="slot-actions">
            <RouterLink class="shop-link" :to="shopLink(slot)">
              浏览{{ slotLabel(slot) }} <ArrowRight aria-hidden="true" />
            </RouterLink>
          </div>
        </section>
        <section>
          <h2>空间头图</h2>
          <p>支持 JPG、PNG、GIF 或 WebP，最大 15 MB。推荐上传 1920 × 1080 或更清晰的横图。审核通过后公开，等待期间访客继续看到原头图。</p>
          <div v-if="pending" class="banner-review-status">
            <strong>新头图待审核</strong>
            <button type="button" :disabled="!!busy" @click="load">刷新结果</button>
            <button type="button" :disabled="!!busy" @click="withdrawBanner">撤回</button>
          </div>
          <p v-else-if="review?.state === 'REJECTED'" role="status">审核未通过 · {{ review.reason }}</p>
          <p v-else-if="review?.state === 'APPROVED' && catalog.appearance.spaceBannerUrl" role="status">头图已通过审核并公开。</p>
          <p v-if="previewError" role="alert">{{ previewError }}</p>
          <label class="banner-file">
            <span>{{ busy === 'upload' ? '上传中 ' + uploadProgress + '%' : '上传头图' }}</span>
            <input type="file" accept=".jpg,.jpeg,.png,.gif,.webp" :disabled="!!busy" @change="uploadBanner">
          </label>
          <button v-if="catalog.appearance.spaceBannerUrl" type="button" class="remove-banner" :disabled="!!busy" @click="removeBanner">移除已公开头图</button>
        </section>
      </aside>
    </div>
    <p v-if="message" class="customization-feedback" role="status">{{ message }}</p>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import ContentState from '@/components/ContentState.vue'
import SpaceBanner from '@/components/SpaceBanner.vue'
import SpaceAvatar from '@/components/SpaceAvatar.vue'
import BubblePreview from '@/components/BubblePreview.vue'
import SpaceIcon from '@/components/SpaceIcon.vue'
import { rememberPendant } from '@/utils/pendantDirectory'
import { rememberSiteIconPack } from '@/utils/siteIconPack'
import { errorMessage } from '@/utils/feedback'
import request from '@/utils/request'
import { uploadFile } from '@/utils/upload'
import { artworkCover, avatarPendantSlot, bannerView, chatBubbleSlot, decorationSlots, pendantImage, readySlotKeys,
  slotLabel, spaceBannerRatios, spaceIconsSlot, type SpaceAppearance, type SpaceArtwork, type SpaceCatalog, type BannerReview } from '@/utils/spaceSkins'

const endpoint = '/user/space-customization'
const route = useRoute()
const reviewEndpoint = endpoint + '/banner-review'
const catalog = ref<SpaceCatalog>()
const profile = ref<{ avatar?: string, nickName?: string, personIntroduction?: string }>()
const framing = ref(bannerView())
const uploadProgress = ref(0)
const loading = ref(false)
const loadError = ref('')
const busy = ref('')
const message = ref('')
const review = ref<BannerReview | null>(null)
const privateImage = ref('')
const previewError = ref('')
const pending = computed(() => review.value?.state === 'PENDING' ? review.value : null)
const savedFraming = computed(() => {
  if (pending.value) return bannerView(pending.value.view, pending.value.position)
  return bannerView(catalog.value?.appearance.spaceBannerView, catalog.value?.appearance.spaceBannerPosition)
})
const framingChanged = computed(() => framing.value.ratio !== savedFraming.value.ratio
  || framing.value.x !== savedFraming.value.x || framing.value.y !== savedFraming.value.y)
const previewUrl = computed(() => pending.value ? privateImage.value : catalog.value?.appearance.spaceBannerUrl)
/** Slots a user wears one artwork in. A slot appears here as soon as the contract marks it ready. */
const wearableSlots = readySlotKeys.filter(key => decorationSlots[key]?.usage === 'wear')
/** Slots where every owned artwork is usable at once, such as sticker packs. */
const collectedSlots = readySlotKeys.filter(key => decorationSlots[key]?.usage === 'collect')
/** The artwork being tried on per slot; an empty string previews the slot without decoration. */
const previewIds = ref<Record<string, string>>({})
let disposed = false

function candidates(slot: string) {
  return catalog.value?.artworks.filter(art => art.slot === slot) ?? []
}

function owned(slot: string) {
  return candidates(slot).filter(art => catalog.value?.ownedArtworks.includes(art.artworkId))
}

function wornId(slot: string) {
  return catalog.value?.appearance.equippedArtworks[slot]?.artworkId ?? ''
}

/** Only owned artworks are previewed here; unowned ones are shown in the shop. */
function previewArtwork(slot: string) {
  return owned(slot).find(art => art.artworkId === previewIds.value[slot])
}

function artworkLabel(art: SpaceArtwork) {
  return art.artworkId === wornId(art.slot) ? '使用中' : '已拥有'
}

/** Opens the shop on this slot's category. */
function shopLink(slot: string) {
  return { path: '/growth-shop', query: { tab: 'skins', type: slot } }
}

function resetPreviews() {
  previewIds.value = Object.fromEntries(wearableSlots.map(slot => [slot, wornId(slot)]))
}

function clearPrivateImage() {
  if (privateImage.value) URL.revokeObjectURL(privateImage.value)
  privateImage.value = ''
}

async function showReview(next: BannerReview | null) {
  clearPrivateImage()
  review.value = next
  framing.value = { ...savedFraming.value }
  previewError.value = ''
  if (next?.state !== 'PENDING') return
  try {
    const image: unknown = await request.get(reviewEndpoint + '/' + next.reviewId + '/image', { responseType: 'blob' })
    if (disposed || review.value?.reviewId !== next.reviewId) return
    if (!(image instanceof Blob) || image.type !== 'image/webp') throw new Error('暂时无法预览待审核头图')
    privateImage.value = URL.createObjectURL(image)
  } catch (error) {
    if (!disposed && review.value?.reviewId === next.reviewId) previewError.value = errorMessage(error, '请刷新预览')
  }
}

function updateAppearance(appearance: SpaceAppearance) {
  if (!catalog.value) return
  catalog.value.appearance = appearance
}

async function load() {
  if (loading.value || disposed) return
  loading.value = true
  loadError.value = ''
  try {
    const userId = localStorage.getItem('userId')
    if (!userId) throw new Error('找不到当前账号，请重新登录')
    const profileRequest = request.get('/user/space/' + userId).then(result => {
      if (!result.data || typeof result.data !== 'object' || Array.isArray(result.data)) throw new Error('资料格式异常')
      return result.data
    }).catch(error => { throw new Error('个人资料加载失败。' + errorMessage(error, '请稍后重试')) })
    const [response, submission, user] = await Promise.all([request.get(endpoint), request.get(reviewEndpoint), profileRequest])
    if (disposed) return
    const data: SpaceCatalog = response.data
    if (!data?.appearance || !Array.isArray(data.products) || !Array.isArray(data.artworks)) throw new Error('装扮目录格式异常')
    profile.value = user
    catalog.value = data
    resetPreviews()
    const requested = data.artworks.find(art => art.artworkId === route.query.artwork && wearableSlots.includes(art.slot)
      && data.ownedArtworks.includes(art.artworkId))
    if (requested) previewIds.value[requested.slot] = requested.artworkId
    await showReview(submission.data)
  } catch (error) {
    if (!disposed) loadError.value = errorMessage(error, '请稍后重试')
  } finally {
    loading.value = false
  }
}

async function change(action: string, work: () => Promise<void>, success: string) {
  if (busy.value) return
  busy.value = action
  message.value = ''
  try {
    await work()
    message.value = success
  } catch (error) {
    message.value = errorMessage(error, '操作失败，请重试')
  } finally {
    busy.value = ''
  }
}

async function wear(slot: string, artworkId: string) {
  const owner = localStorage.getItem('userId')
  await change('wear', async () => {
    const url = endpoint + '/artworks/' + slot
    const response = artworkId ? await request.put(url, { artworkId }) : await request.delete(url)
    updateAppearance(response.data)
    if (slot === avatarPendantSlot) {
      rememberPendant(owner, pendantImage(response.data.equippedArtworks?.[slot]))
    }
    if (slot === spaceIconsSlot) {
      rememberSiteIconPack(owner, response.data.equippedArtworks?.[slot])
    }
    previewIds.value[slot] = wornId(slot)
  }, artworkId ? `已使用${slotLabel(slot)}` : `已取消${slotLabel(slot)}`)
}

async function uploadBanner(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !catalog.value) return
  if (file.size > 15 * 1024 * 1024) { message.value = '图片不能超过 15 MB'; return }
  uploadProgress.value = 0
  await change('upload', async () => {
    const result = await uploadFile<BannerReview>({ url: '/file/upload-space-banner', file, onProgress: progress => { uploadProgress.value = progress } })
    if (result.code !== 200 || !result.data?.reviewId) throw new Error(result.message || '上传失败')
    await showReview(result.data)
  }, '头图已提交审核')
}

async function savePosition() {
  const url = catalog.value?.appearance.spaceBannerUrl
  const submission = pending.value
  if (!url && !submission) return
  const input = { position: framing.value.y, view: framing.value }
  await change('position', async () => {
    if (submission) {
      const response = await request.put(reviewEndpoint + '/' + submission.reviewId + '/position', input)
      review.value = response.data
    } else {
      const response = await request.put(endpoint + '/banner-position', { url, ...input })
      updateAppearance(response.data)
    }
  }, '头图位置已保存')
}

async function withdrawBanner() {
  const submission = pending.value
  if (!submission) return
  await change('withdraw', async () => {
    await request.delete(reviewEndpoint + '/' + submission.reviewId)
    await showReview(null)
  }, '头图已撤回')
}

async function removeBanner() {
  await change('remove', async () => {
    const response = await request.delete(endpoint + '/banner')
    updateAppearance(response.data)
    if (!pending.value) framing.value = { ...savedFraming.value }
  }, '已恢复默认头图')
}

onMounted(load)
onUnmounted(() => { disposed = true; clearPrivateImage() })
</script>

<style scoped>
.space-customization { max-width: 1200px; margin: auto; min-height: 100vh; padding: 110px 28px 48px; }
.customization-heading a { color: var(--ej-muted); font-size: 14px; }
.customization-heading h1 { margin: 10px 0 24px; font-size: clamp(34px, 5vw, 52px); letter-spacing: -.045em; }
.customization-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 340px); gap: 24px; align-items: start; }
.preview-card, .customization-options section, .position-row { background: var(--ej-surface); border: 1px solid var(--ej-ink); border-radius: 20px; box-shadow: var(--ej-shadow); }
.preview-card { overflow: hidden; }
.preview-profile { position: relative; padding: 0 24px 24px; }
.preview-profile:has(.with-pendant) { padding-inline: 34px; }
.preview-avatar { margin-top: -42px; border: 3px solid var(--ej-surface); box-shadow: var(--ej-shadow); }
.preview-avatar.with-pendant { margin-bottom: 24px; }
.preview-profile h2 { margin: 12px 0 8px; }
.preview-profile p { margin: 0 0 12px; color: var(--ej-muted); overflow-wrap: anywhere; }
.customization-options { display: grid; gap: 24px; }
.customization-options section, .position-row { padding: 20px; }
.customization-options h2 { margin: 0 0 12px; font-size: 19px; }
.customization-options p { color: var(--ej-muted); font-size: 13px; margin: 0 0 14px; line-height: 1.5; }
.banner-review-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 13px; }
.artwork-options { display: grid; gap: 6px; margin-bottom: 15px; }
.artwork-options button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 6px 10px; border: 1px solid var(--ej-line); border-radius: 9px; background: var(--ej-surface); color: var(--ej-ink); text-align: left; }
.artwork-options button[aria-pressed=true] { border-color: var(--ej-ink); background: var(--ej-accent-soft); }
.artwork-options small { margin-left: auto; color: var(--ej-muted); white-space: nowrap; }
/* 选中行底色更深，状态文字用正文色保证可读 */
.artwork-options button[aria-pressed=true] small { color: var(--ej-body); }
.artwork-thumb { flex: none; width: 40px; height: 40px; object-fit: contain; }
.artwork-thumb.empty { border: 1px dashed var(--ej-line); border-radius: 50%; }
.position-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 12px; margin-top: 16px; }
.position-row input { width: 100%; accent-color: var(--ej-accent); }
.position-row button { grid-column: 1 / -1; justify-self: start; }
.position-row select {
  background: var(--ej-surface); color: var(--ej-ink); border: 1px solid var(--ej-line);
  border-radius: 8px; padding: 7px 9px; min-width: 0;
}
:is(.customization-action, .position-row button, .remove-banner, .remove-artwork) {
  display: inline-block; padding: 7px 14px; text-decoration: none; border: 1px solid var(--ej-ink); border-radius: 999px; color: var(--ej-ink); background: var(--ej-surface);
}
.customization-action { background: var(--ej-ink); color: var(--ej-surface); }
.slot-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
.shop-link {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 7px 13px;
  border: 1px solid var(--ej-line); border-radius: 999px; background: var(--ej-canvas);
  color: var(--ej-ink); font-size: 13px; font-weight: 600; text-decoration: none;
}
.shop-link:not(:only-child) { margin-inline-start: auto; }
.shop-link svg { width: 12px; height: 12px; }
.shop-link:hover, .shop-link:focus-visible { border-color: var(--ej-ink); background: var(--ej-accent-soft); }
:is(.customization-action, .position-row button, .remove-artwork):disabled, .remove-banner:disabled { opacity: .55; }
.banner-file { position: relative; display: inline-flex; align-items: center; margin-right: 8px; color: var(--ej-ink); }
.banner-file span { border: 1px solid var(--ej-ink); border-radius: 999px; padding: 7px 14px; cursor: pointer; }
.banner-file:focus-within span { outline: 2px solid var(--ej-accent); outline-offset: 4px; }
.banner-file input { position: absolute; width: 1px; height: 1px; clip-path: inset(50%); }
.banner-file:has(input:disabled) span { opacity: .55; cursor: default; }
.remove-banner { margin-top: 12px; }
.preview-bubbles { margin-top: 16px; }
.preview-icons { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.preview-icon { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border: 1px solid var(--ej-line); border-radius: 999px; background: var(--ej-surface); color: var(--ej-ink); font-size: 13px; }
.icon-default { display: inline-grid; place-items: center; width: 1.25em; color: var(--ej-muted); }
.collection-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.collection-row div { display: grid; gap: 2px; }
.collection-row small { color: var(--ej-muted); font-size: 12px; }
.customization-feedback { margin: 18px 0; color: var(--ej-ink); }
@media (max-width: 760px) {
  .space-customization { padding: 86px 16px 32px; }
  .customization-layout { grid-template-columns: 1fr; gap: 16px; }
}
</style>
