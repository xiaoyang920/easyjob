<template>
  <section class="banner-review-panel">
    <ContentState v-if="loading" kind="loading" title="正在加载头图" />
    <ContentState v-else-if="loadError" kind="error" title="审核列表暂时不可用" :description="loadError" @retry="reload" />
    <ContentState v-else-if="!submissions.length" kind="empty" title="暂无待审核头图" />
    <ul v-else class="banner-review-list">
      <li v-for="item in submissions" :key="item.reviewId">
        <div><strong>{{ item.nickname || '用户 ' + item.userId }}</strong><small>{{ item.createdAt.replace('T', ' ').slice(0, 16) }}</small></div>
        <button type="button" :aria-expanded="selected?.reviewId === item.reviewId" :disabled="busy" @click="preview(item)">审核预览</button>
      </li>
    </ul>
    <div v-if="page > 1 || more" class="banner-review-pagination">
      <button type="button" :disabled="page <= 1 || loading || busy" @click="turn(-1)">上一页</button>
      <span>第 {{ page }} 页</span>
      <button type="button" :disabled="!more || loading || busy" @click="turn(1)">下一页</button>
    </div>
    <article v-if="selected" class="banner-review-card">
      <h2>{{ selected.nickname || '用户 ' + selected.userId }}的待审核头图</h2>
      <p v-if="previewLoading" role="status">正在加载预览…</p>
      <p v-if="message" role="status">{{ message }}</p>
      <SpaceBanner v-if="imageUrl" :url="imageUrl" :position="selected.view?.y ?? selected.position"
        :x="selected.view?.x" :ratio="selected.view?.ratio" />
      <form v-if="canManage && imageUrl" class="banner-review-actions" @submit.prevent="decide(false)">
        <label for="space-banner-rejection">驳回原因</label>
        <textarea id="space-banner-rejection" v-model="reason" maxlength="300" rows="3" :disabled="busy" placeholder="驳回时请填写原因"></textarea>
        <div>
          <button type="submit" :disabled="busy || !reason.trim()">驳回</button>
          <button type="button" class="approve-banner" :disabled="busy" @click="decide(true)">通过并公开</button>
        </div>
      </form>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import ContentState from './ContentState.vue'
import SpaceBanner from './SpaceBanner.vue'
import request from '@/utils/request'
import { errorMessage } from '@/utils/feedback'
import type { BannerReview } from '@/utils/spaceSkins'

defineProps<{ canManage: boolean }>()
const endpoint = '/admin/space-banners'
const pageSize = 12
const page = ref(1), more = ref(false)
const submissions = ref<BannerReview[]>([])
const selected = ref<BannerReview>()
const imageUrl = ref('')
const reason = ref('')
const message = ref('')
const loadError = ref('')
const loading = ref(false), busy = ref(false), previewLoading = ref(false)
let previewGeneration = 0

function clearPreview() {
  previewGeneration++
  selected.value = undefined
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
  message.value = ''
  reason.value = ''
  previewLoading.value = false
}

async function reload() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  clearPreview()
  try {
    const response = await request.get(endpoint, { params: { page: page.value, size: pageSize } })
    submissions.value = response.data
    more.value = submissions.value.length === pageSize
  } catch (error) {
    loadError.value = errorMessage(error, '请刷新后重试')
  } finally {
    loading.value = false
  }
}

function turn(delta: number) {
  page.value += delta
  void reload()
}

function reviewPath(item: BannerReview) {
  return endpoint + '/' + item.userId + '/' + item.reviewId
}

async function preview(item: BannerReview) {
  clearPreview()
  selected.value = item
  previewLoading.value = true
  const generation = previewGeneration
  try {
    const photo: unknown = await request.get(reviewPath(item) + '/image', { responseType: 'blob' })
    if (generation !== previewGeneration) return
    if (!(photo instanceof Blob) || photo.type !== 'image/webp') throw new Error('头图已变化，请刷新列表')
    imageUrl.value = URL.createObjectURL(photo)
  } catch (error) {
    if (generation === previewGeneration) message.value = errorMessage(error, '无法加载待审核头图')
  } finally {
    if (generation === previewGeneration) previewLoading.value = false
  }
}

async function decide(approved: boolean) {
  const item = selected.value
  if (!item || !imageUrl.value || busy.value) return
  busy.value = true
  message.value = ''
  try {
    await request.post(reviewPath(item), { approved, reason: approved ? '' : reason.value.trim() })
    page.value = 1
    await reload()
  } catch (error) {
    message.value = errorMessage(error, '提交失败，请重试')
  } finally {
    busy.value = false
  }
}

defineExpose({ reload })
onMounted(reload)
onUnmounted(clearPreview)
</script>

<style scoped>
.banner-review-panel { display: grid; gap: 16px; }
.banner-review-list, .banner-review-card { border: 1px solid var(--ej-ink); background: var(--ej-surface); border-radius: 16px; padding: 18px; }
.banner-review-list { display: grid; gap: 8px; list-style: none; }
.banner-review-list li, .banner-review-pagination, .banner-review-actions > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.banner-review-list small { display: block; color: var(--ej-muted); margin-top: 4px; }
.banner-review-card h2 { margin: 0 0 12px; font-size: 17px; }
.banner-review-card :deep(.space-banner) { border-radius: 10px; }
.banner-review-actions { display: grid; gap: 8px; margin-top: 14px; }
.banner-review-actions textarea { background: var(--ej-canvas); color: var(--ej-ink); border: 1px solid var(--ej-line); border-radius: 8px; padding: 8px; }
.banner-review-actions > div { justify-content: flex-end; }
.banner-review-actions .approve-banner { background: var(--ej-ink); color: var(--ej-surface); }
</style>
