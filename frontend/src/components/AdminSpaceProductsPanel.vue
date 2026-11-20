<template>
  <section class="space-products-admin">
    <nav class="product-actions" aria-label="装扮商品管理">
      <button v-for="item in panels" :key="item.value" type="button" :disabled="!!busy"
        :aria-pressed="panel === item.value" @click="selectPanel(item.value)">{{ item.label }}</button>
      <RouterLink to="/growth-shop?tab=skins">查看商城</RouterLink>
    </nav>
    <p v-if="message" role="status" class="product-feedback">{{ message }}</p>
    <p v-if="actionError" role="alert" class="product-error">{{ actionError }}</p>
    <ContentState v-if="loadError" kind="error" title="装扮商品加载失败" :description="loadError" @retry="reload" />
    <ContentState v-else-if="!catalog" kind="loading" title="正在加载装扮商品" />
    <template v-else>
      <ArtworkEditor v-if="panel === 'upload'" @busy="busy = $event ? 'upload' : ''" @saved="artworkSaved" />
      <div v-else-if="panel === 'list'" class="product-list">
        <ContentState v-if="!products.length" kind="empty" title="暂无装扮商品" />
        <form v-for="product in products" :key="product.productId" class="product-row" @submit.prevent="saveProduct(product)">
          <img v-if="artworkOf(product)" class="product-thumb" :src="artworkCover(artworkOf(product))" alt="" width="56" height="56">
          <span v-else class="product-thumb" aria-hidden="true"></span>
          <div class="product-title">
            <strong>{{ product.name }}</strong>
            <span v-if="!product.standaloneArtworkId">套装 · 含 {{ Object.keys(product.artworks).length }} 件</span>
            <span v-else>{{ artworkOf(product) ? slotLabel(artworkOf(product)!.slot) + ' · ' + artworkOf(product)!.artist : '作品已撤回' }}</span>
          </div>
          <label>商品名称<input v-model.trim="product.name" required maxlength="60" :disabled="!!busy"></label>
          <label>硬币价格<input v-model.number="product.coinPrice" type="number" required min="1" max="2147483647" :disabled="!!busy"></label>
          <label>排序<input v-model.number="product.sortOrder" type="number" required min="0" max="100000" :disabled="!!busy"></label>
          <label>状态
            <select v-model="product.listed" :disabled="!!busy">
              <option :value="true">已上架</option>
              <option :value="false">已下架</option>
            </select>
          </label>
          <button class="product-primary" :disabled="!!busy" type="submit">保存修改</button>
        </form>
        <p v-if="products.length" class="product-note">排序数字越小，商品越靠前。下架后，已拥有的用户仍可佩戴。</p>
      </div>
      <div v-else-if="panel === 'artworks'" class="product-list">
        <ContentState v-if="!catalog.artworks.length" kind="empty" title="作品库还是空的" />
        <article v-for="art in catalog.artworks" :key="art.artworkId" class="artwork-row">
          <img :src="artworkCover(art)" alt="" width="60" height="60">
          <form v-if="editingArt && editingArt.artworkId === art.artworkId" class="product-fields" @submit.prevent="saveArtwork">
            <label>作品名称<input v-model.trim="editingArt.name" maxlength="60" required :disabled="!!busy"></label>
            <label>作者署名<input v-model.trim="editingArt.artist" maxlength="60" required :disabled="!!busy"></label>
            <div class="artwork-actions">
              <button type="submit" :disabled="!!busy">保存作品信息</button>
              <button type="button" :disabled="!!busy" @click="editingArt = undefined">取消</button>
            </div>
          </form>
          <template v-else>
            <div class="product-title"><strong>{{ art.name }}</strong><span>{{ slotLabel(art.slot) }} · {{ art.artist }}</span></div>
            <button type="button" :disabled="!!busy" @click="editingArt = { ...art }">编辑作品信息</button>
            <button type="button" :disabled="!!busy" @click="withdrawArtwork(art)">撤回作品</button>
          </template>
        </article>
        <p v-if="catalog.artworks.length" class="product-note">已售出或仍在上架的作品不能撤回。</p>
      </div>
      <div v-else class="product-editor">
        <form class="product-fields" @submit.prevent="publish">
          <label>销售方式
            <select v-model="saleType" :disabled="!!busy">
              <option value="single">单品（一件作品）</option>
              <option value="bundle">套装（每个部位最多一件）</option>
            </select>
          </label>
          <template v-if="saleType === 'single'">
            <label>选择作品
              <select v-model="artworkId" required :disabled="!!busy">
                <option value="" disabled>选择一件作品</option>
                <option v-for="art in unsoldArtworks" :key="art.artworkId" :value="art.artworkId">
                  {{ slotLabel(art.slot) }} · {{ art.name }} · {{ art.artist }}
                </option>
              </select>
            </label>
            <p v-if="!unsoldArtworks.length" class="product-note">作品库里的作品都已建立单品。先上传新作品再上架。</p>
          </template>
          <template v-else>
            <label v-for="slot in readySlotKeys" :key="slot">{{ slotLabel(slot) }}
              <select v-model="bundle[slot]" :disabled="!!busy">
                <option value="">不包含</option>
                <option v-for="art in catalog.artworks.filter(item => item.slot === slot)" :key="art.artworkId" :value="art.artworkId">
                  {{ art.name }} · {{ art.artist }}
                </option>
              </select>
            </label>
            <p class="product-note">至少选择 2 件。已拥有其中部分作品的用户，按未拥有的件数比例折价，向上取整，最少 1 硬币。</p>
          </template>
          <label>商品名称<input v-model.trim="productName" required maxlength="60" :disabled="!!busy"></label>
          <label>硬币价格<input v-model.number="price" type="number" required min="1" max="2147483647" :disabled="!!busy"></label>
          <button class="product-primary" :disabled="!!busy || !publishable" type="submit">上架商品</button>
        </form>
        <SpaceProductPreview :artworks="selectedArtworks" />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ContentState from './ContentState.vue'
import SpaceProductPreview from './SpaceProductPreview.vue'
import ArtworkEditor from './ArtworkEditor.vue'
import request from '@/utils/request'
import { confirmAction, errorMessage } from '@/utils/feedback'
import { artworkCover, productArtworks, readySlotKeys, slotLabel, spaceRequestId,
  type AdminSpaceCatalog, type SpaceArtwork, type SpaceProduct } from '@/utils/spaceSkins'

const endpoint = '/admin/space-skins'
const panels = [
  { value: 'list', label: '商品列表' }, { value: 'publish', label: '上架作品' },
  { value: 'artworks', label: '作品库' }, { value: 'upload', label: '上传作品' }
] as const
type Panel = typeof panels[number]['value']
const panel = ref<Panel>('list')
const catalog = ref<AdminSpaceCatalog>()
const products = ref<SpaceProduct[]>([])
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const message = ref('')
const busy = ref('')
const editingArt = ref<SpaceArtwork>()
const artworkId = ref('')
const productName = ref('')
const price = ref<number | string>('')
let publishAttempt: { key: string, id: string } | undefined

const unsoldArtworks = computed(() => {
  const sold = new Set(catalog.value?.products.map(product => product.standaloneArtworkId))
  return catalog.value?.artworks.filter(art => !sold.has(art.artworkId)) ?? []
})
const saleType = ref<'single' | 'bundle'>('single')
/** Bundle composition: one artwork id per slot, empty when the slot is left out. */
const bundle = ref<Record<string, string>>({})
const selectedIds = computed(() => saleType.value === 'single'
  ? (artworkId.value ? [artworkId.value] : [])
  : readySlotKeys.map(slot => bundle.value[slot]).filter((id): id is string => !!id))
const selectedArtworks = computed(() => selectedIds.value.flatMap(id => {
  const artwork = catalog.value?.artworks.find(art => art.artworkId === id)
  return artwork ? [artwork] : []
}))
const publishable = computed(() => saleType.value === 'single' ? selectedIds.value.length === 1 : selectedIds.value.length >= 2)

/** The product's first artwork, used for its thumbnail in the product list. */
function artworkOf(product: SpaceProduct) {
  return productArtworks(product, catalog.value?.artworks ?? [])[0]
}

function selectPanel(next: Panel) {
  editingArt.value = undefined
  panel.value = next
}

async function artworkSaved(id: string, name: string) {
  await reload()
  saleType.value = 'single'
  artworkId.value = id
  productName.value = name
  price.value = ''
  panel.value = 'publish'
  message.value = '作品已保存，填写价格即可上架'
}

async function reload() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const response = await request.get(endpoint)
    const data: AdminSpaceCatalog = response.data
    if (!Array.isArray(data?.products) || !Array.isArray(data.artworks)) throw new Error('装扮目录格式异常')
    catalog.value = data
    products.value = data.products.map(product => ({ ...product }))
  } catch (error) {
    loadError.value = errorMessage(error, '请稍后重试')
  } finally {
    loading.value = false
  }
}

async function run(action: string, work: () => Promise<void>) {
  if (busy.value || loading.value) return
  busy.value = action
  message.value = ''
  actionError.value = ''
  try { await work() }
  catch (error) { actionError.value = errorMessage(error, '操作失败，请重试') }
  finally { busy.value = '' }
}

async function saveProduct(product: SpaceProduct) {
  await run(product.productId, async () => {
    const response = await request.put(endpoint + '/' + product.productId, {
      name: product.name, price: product.coinPrice, sortOrder: product.sortOrder, listed: product.listed, version: product.version
    })
    const saved: SpaceProduct = response.data
    products.value = products.value.map(item => item.productId === saved.productId ? { ...saved } : item)
      .sort((a, b) => a.sortOrder - b.sortOrder || a.productId.localeCompare(b.productId))
    message.value = '商品已更新'
  })
}

async function publish() {
  if (typeof price.value !== 'number' || !publishable.value) return
  const input = { name: productName.value, price: price.value, artworkIds: [...selectedIds.value] }
  const key = JSON.stringify(input)
  if (publishAttempt?.key !== key) publishAttempt = { key, id: spaceRequestId('product') }
  const id = publishAttempt.id
  await run('publish', async () => {
    await request.post(endpoint, { ...input, id })
    publishAttempt = undefined
    artworkId.value = ''
    bundle.value = {}
    productName.value = ''
    price.value = ''
    panel.value = 'list'
    message.value = '商品已上架'
    await reload()
  })
}

async function saveArtwork() {
  const art = editingArt.value
  if (!art) return
  await run('edit-artwork', async () => {
    await request.put(endpoint + '/artworks/' + art.artworkId, { name: art.name, artist: art.artist, version: art.version })
    editingArt.value = undefined
    message.value = '作品信息已更新'
    await reload()
  })
}

async function withdrawArtwork(art: SpaceArtwork) {
  await run('withdraw-artwork', async () => {
    if (!await confirmAction('撤回「' + art.name + '」？撤回后将从作品库移除。', '撤回作品')) return
    await request.delete(endpoint + '/artworks/' + art.artworkId, { params: { version: art.version } })
    message.value = '作品已撤回'
    await reload()
  })
}

defineExpose({ reload })
onMounted(reload)
</script>

<style scoped>
.space-products-admin { display: grid; gap: 16px; }
.product-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.product-actions a { margin-left: auto; color: var(--ej-accent); font-size: 13px; }
.product-actions button, .product-primary, .artwork-row button {
  padding: 7px 14px; border: 1px solid var(--ej-ink); border-radius: 999px;
  color: var(--ej-ink); background: var(--ej-surface);
}
.product-actions button[aria-pressed=true], .product-primary {
  background: var(--studio-lime); color: var(--ej-on-color);
}
.product-primary:disabled { opacity: .55; }
.product-list { display: grid; gap: 12px; }
.product-row, .product-editor, .artwork-row {
  display: grid; gap: 12px; padding: 18px; align-items: end;
  border: 1px solid var(--ej-line); border-radius: 16px; background: var(--ej-surface);
}
.product-row { grid-template-columns: 56px minmax(125px, 1fr) minmax(130px, 1.1fr) repeat(3, minmax(0, .6fr)) auto; }
.product-thumb { width: 56px; height: 56px; align-self: center; object-fit: contain; }
.artwork-row { grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; }
.artwork-row img { object-fit: contain; }
.artwork-row form { grid-column: 2 / -1; }
.artwork-actions { display: flex; gap: 8px; }
.product-title { display: grid; align-self: center; gap: 4px; overflow-wrap: anywhere; }
.product-title span, .product-note { color: var(--ej-muted); font-size: 13px; }
.product-editor { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); align-items: start; gap: 24px; }
.product-fields { display: grid; gap: 12px; }
.product-editor :deep(.product-art) { border: 1px solid var(--ej-line); border-radius: 16px; }
.space-products-admin label { display: grid; gap: 5px; color: var(--ej-muted); font-size: 13px; }
.space-products-admin :is(select, input) {
  width: 100%; padding: 7px 9px; border: 1px solid var(--ej-line); border-radius: 8px;
  color: var(--ej-ink); background: var(--ej-surface);
}
.product-feedback, .product-error { padding: 9px 12px; margin: 0; border-radius: 8px; font-size: 14px; }
.product-feedback { background: var(--ej-accent-soft); color: var(--ej-ink); }
.product-error { background: var(--ej-surface); border: 1px solid var(--ej-ink); color: var(--ej-ink); }
@media (max-width: 1150px) { .product-row { grid-template-columns: 56px repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .product-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .product-editor { grid-template-columns: 1fr; }
  .artwork-row { grid-template-columns: auto 1fr; }
}
</style>
