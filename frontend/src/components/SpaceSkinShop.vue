<template>
  <div class="skin-shop">
    <ContentState v-if="loading && !catalog" kind="loading" title="正在加载空间装扮" />
    <ContentState v-else-if="loadError" kind="error" title="空间装扮暂时无法加载" :description="loadError" @retry="load" />
    <template v-else-if="catalog">
      <div class="skin-filters" role="group" aria-label="装扮分类">
        <button v-for="item in filters" :key="item.value" type="button" :aria-pressed="filter === item.value"
          @click="filter = item.value">{{ item.label }}</button>
      </div>
      <ContentState v-if="!products.length" kind="empty" title="暂无该类装扮" />
      <div v-else class="skin-products">
        <article v-for="product in products" :key="product.productId" class="skin-product">
          <SpaceProductPreview :artworks="partsOf(product)" />
          <div class="skin-details">
            <div>
              <h3>{{ product.name }}</h3>
              <p v-if="product.owned">{{ kindLabel(product) }} · 已拥有</p>
              <p v-else>{{ kindLabel(product) }} · <template v-if="discounted(product)"><s>{{ product.coinPrice }}</s> </template>{{ priceOf(product) }} 硬币</p>
              <p v-if="discounted(product)">已拥有其中 {{ quoteOf(product)?.ownedArtworks }} 件，按未拥有的部分折价</p>
              <p v-if="authors(product)">作者 · {{ authors(product) }}</p>
            </div>
            <button v-if="wearing(product)" type="button" disabled>使用中</button>
            <button v-else-if="product.owned && isSingleWearable(product)" type="button" :disabled="!!busy" @click="wear(product)">
              {{ busy === product.productId ? '处理中…' : '使用' }}
            </button>
            <RouterLink v-else-if="product.owned && wearablePart(product)" class="shop-link" to="/space-customization">去装扮</RouterLink>
            <button v-else-if="product.owned" type="button" disabled>已拥有</button>
            <button v-else type="button" :disabled="!!busy" @click="purchase(product)">
              {{ busy === product.productId ? '购买中…' : '购买' }}
            </button>
          </div>
        </article>
      </div>
    </template>
    <p v-if="message" role="status" class="skin-feedback">{{ message }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'
import { useRoute } from 'vue-router'
import ContentState from './ContentState.vue'
import SpaceProductPreview from './SpaceProductPreview.vue'
import request from '@/utils/request'
import { confirmAction, errorMessage } from '@/utils/feedback'
import { rememberPendant } from '@/utils/pendantDirectory'
import { rememberSiteIconPack } from '@/utils/siteIconPack'
import { avatarPendantSlot, decorationSlots, pendantImage, productArtworks, readySlotKeys, slotLabel, spaceIconsSlot, type SpaceCatalog, type SpaceProduct } from '@/utils/spaceSkins'

const endpoint = '/user/space-customization'
const emit = defineEmits<{ balance: [value: number]; purchaseCompleted: [] }>()
const catalog = ref<SpaceCatalog>()
const loading = ref(false)
const loadError = ref('')
const busy = ref('')
const message = ref('')
const owner = localStorage.getItem('userId') || ''
/** Filters follow the contract, so a new slot gets its own shop category automatically. */
const filters = [{ value: 'all', label: '全部' }, { value: 'bundle', label: '套装' },
  ...readySlotKeys.map(slot => ({ value: slot, label: slotLabel(slot) }))]
const route = useRoute()
const filter = ref(filters.some(item => item.value === route.query.type) ? String(route.query.type) : 'all')
/** Listed products plus everything the user already owns, including products taken off sale or gifted. */
const products = computed(() => catalog.value?.products.filter(product => (product.listed || product.owned)
  && (filter.value === 'all' || kindOf(product) === filter.value)) ?? [])

function partsOf(product: SpaceProduct) {
  return productArtworks(product, catalog.value?.artworks ?? [])
}

function kindOf(product: SpaceProduct) {
  return product.standaloneArtworkId ? partsOf(product)[0]?.slot : 'bundle'
}

function kindLabel(product: SpaceProduct) {
  return product.standaloneArtworkId ? slotLabel(partsOf(product)[0]?.slot ?? '') : `套装 · 含 ${partsOf(product).length} 件`
}

function authors(product: SpaceProduct) {
  return [...new Set(partsOf(product).map(part => part.artist))].join('、')
}

function quoteOf(product: SpaceProduct) {
  return catalog.value?.quotes[product.productId]
}

function priceOf(product: SpaceProduct) {
  return quoteOf(product)?.price ?? product.coinPrice
}

function discounted(product: SpaceProduct) {
  return !product.owned && priceOf(product) !== product.coinPrice
}

/** The first part this product grants that can be worn, used for the try-on link. */
function wearablePart(product: SpaceProduct) {
  return partsOf(product).find(part => decorationSlots[part.slot]?.usage === 'wear')
}

function isSingleWearable(product: SpaceProduct) {
  return !!product.standaloneArtworkId && !!wearablePart(product)
}

function wearing(product: SpaceProduct) {
  const part = isSingleWearable(product) ? wearablePart(product) : undefined
  return !!part && catalog.value?.appearance.equippedArtworks[part.slot]?.artworkId === part.artworkId
}

async function load() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const response = await request.get(endpoint)
    const data: SpaceCatalog = response.data
    if (!data?.appearance || !Array.isArray(data.products) || !Array.isArray(data.artworks) || !data.quotes) {
      throw new Error('装扮目录格式异常')
    }
    catalog.value = data
    emit('balance', data.balance)
  } catch (error) {
    loadError.value = errorMessage(error, '请稍后重试')
  } finally {
    loading.value = false
  }
}

async function wear(product: SpaceProduct) {
  const part = wearablePart(product)
  if (!catalog.value || busy.value || !part) return
  busy.value = product.productId
  message.value = ''
  try {
    const response = await request.put(endpoint + '/artworks/' + part.slot, { artworkId: part.artworkId })
    catalog.value.appearance = response.data
    if (part.slot === avatarPendantSlot) {
      rememberPendant(owner, pendantImage(response.data.equippedArtworks?.[avatarPendantSlot]))
    }
    if (part.slot === spaceIconsSlot) {
      rememberSiteIconPack(owner, response.data.equippedArtworks?.[spaceIconsSlot])
    }
    message.value = '已使用「' + product.name + '」'
  } catch (error) {
    message.value = errorMessage(error, '操作失败，请重试')
  } finally {
    busy.value = ''
  }
}

async function purchase(product: SpaceProduct) {
  if (!catalog.value || busy.value || product.owned) return
  const price = priceOf(product)
  if (catalog.value.balance < price) {
    message.value = '硬币余额不足'
    return
  }
  busy.value = product.productId
  message.value = ''
  let bought = false
  try {
    const note = discounted(product) ? `（已拥有其中 ${quoteOf(product)?.ownedArtworks} 件，原价 ${product.coinPrice}）` : ''
    if (!await confirmAction(`花费 ${price} 枚硬币购买「${product.name}」${note}？`, '购买空间装扮')) return
    const key = `space-product-request:${owner}:${product.productId}`
    let requestId = sessionStorage.getItem(key)
    if (!requestId) {
      requestId = crypto.randomUUID()
      sessionStorage.setItem(key, requestId)
    }
    const response = await request.post(endpoint + '/purchase', { productId: product.productId, requestId, expectedPrice: price })
    sessionStorage.removeItem(key)
    emit('balance', response.data.balance)
    emit('purchaseCompleted')
    message.value = response.message || '购买成功'
    bought = true
  } catch (error) {
    message.value = errorMessage(error, '购买失败，请重试')
  } finally {
    busy.value = ''
  }
  // Owning new artworks changes the price of every bundle that contains them.
  if (bought) await load()
}

defineExpose({ load })
onActivated(load)
</script>

<style scoped>
.skin-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.skin-filters button { padding: 6px 12px; border: 1px solid var(--ej-line); border-radius: 999px; background: var(--ej-surface); color: var(--ej-ink); }
.skin-filters button[aria-pressed="true"] { background: var(--studio-lime); color: var(--ej-on-color); border-color: var(--ej-ink); }
.skin-products { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 235px), 1fr)); gap: 18px; }
.skin-product { overflow: hidden; border: 1px solid var(--ej-ink); border-radius: 18px; background: var(--ej-surface); box-shadow: var(--ej-shadow); }
.skin-details { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 16px; }
.skin-details h3 { margin: 0 0 5px; color: var(--ej-ink); }
.skin-details p { margin: 0; color: var(--ej-muted); font-size: 13px; }
.skin-details > :is(button, a) { font: inherit; font-size: 13px; border: 1px solid var(--ej-ink); border-radius: 999px; padding: 7px 12px; background: var(--ej-ink); color: var(--ej-surface); white-space: nowrap; text-decoration: none; }
.skin-details > :is(button, a):hover:not(:disabled) { background: var(--studio-lime); color: var(--ej-on-color); }
.skin-details button:disabled { background: var(--ej-soft); color: var(--ej-muted); border-color: var(--ej-line); }
.skin-feedback { margin: 16px 0; color: var(--ej-ink); }
</style>
