<template>
  <div class="artwork-editor">
    <form @submit.prevent="save">
      <label>装扮部位
        <select v-model="slotKey" :disabled="busy" @change="resetAssets">
          <option v-for="key in readySlotKeys" :key="key" :value="key">{{ decorationSlots[key]?.label }}</option>
        </select>
      </label>
      <label>作品名称<input v-model.trim="name" required maxlength="60" :disabled="busy"></label>
      <label>作者署名<input v-model.trim="artist" required maxlength="60" :disabled="busy"></label>
      <p v-if="slot.hint">{{ slot.hint }}</p>
      <a v-if="slotKey === avatarPendantSlot" :href="pendantTemplate()" :download="`EasyJob-头像挂件-${pendantGeometry.canvas}.svg`">
        下载 {{ pendantGeometry.canvas }} × {{ pendantGeometry.canvas }} 对位模板
      </a>
      <fieldset v-for="field in slot.images" :key="field.key">
        <legend>{{ field.label }}</legend>
        <p>{{ describeRule(ruleOf(field.rule)) }}</p>
        <input type="file" :accept="accept(field.rule)" :disabled="busy" @change="uploadImage($event, field.key, field.rule)">
        <img v-if="images[field.key]" class="asset-preview" :src="images[field.key]" alt="">
      </fieldset>
      <fieldset v-if="slot.list">
        <legend>{{ slot.list.label }}（{{ items.length }}/{{ slot.list.max }}）</legend>
        <p>{{ describeRule(ruleOf(slot.list.rule)) }}。每张需要 1–{{ slot.list.nameMaxLength }} 字的名称，名称不能重复。</p>
        <input type="file" multiple :accept="accept(slot.list.rule)" :disabled="busy || items.length >= slot.list.max"
          @change="uploadItems($event)">
        <ol class="item-list">
          <li v-for="(item, index) in items" :key="item.url">
            <img :src="item.url" alt="">
            <input v-model.trim="item.name" required :maxlength="slot.list.nameMaxLength" :aria-label="'第 ' + (index + 1) + ' 张的名称'" :disabled="busy">
            <button type="button" :disabled="busy" @click="items.splice(index, 1)">移除</button>
          </li>
        </ol>
      </fieldset>
      <label v-for="setting in slot.settings" :key="setting.key">{{ setting.label }}
        <input v-if="setting.type === 'slice'" v-model.number="settings[setting.key]" type="number" min="1" step="1" required :disabled="busy">
        <input v-else v-model="settings[setting.key]" type="color" required :disabled="busy">
      </label>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="submit" :disabled="busy || !complete">{{ busy ? '处理中…' : '保存作品' }}</button>
    </form>
    <PendantPreview v-if="slotKey === avatarPendantSlot" :url="images.image" />
    <BubblePreview v-else-if="slotKey === chatBubbleSlot" :bubble="{ assets: { images, items: [] }, settings }" />
    <section v-else class="image-preview" aria-label="作品图片">
      <img v-for="url in uploadedUrls" :key="url" :src="url" alt="">
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import PendantPreview from './PendantPreview.vue'
import BubblePreview from './BubblePreview.vue'
import { errorMessage } from '@/utils/feedback'
import { uploadFile } from '@/utils/upload'
import request from '@/utils/request'
import { avatarPendantSlot, chatBubbleSlot, decorationRules, decorationSlots, describeRule, pendantGeometry, pendantTemplate,
  readySlotKeys, spaceRequestId, type DecorationImageRule } from '@/utils/spaceSkins'

const emit = defineEmits<{ saved: [id: string, name: string], busy: [value: boolean] }>()
const endpoint = '/admin/space-skins/artworks'
const slotKey = ref(readySlotKeys[0] ?? '')
const name = ref('')
const artist = ref('')
const images = ref<Record<string, string>>({})
const items = ref<{ name: string, url: string }[]>([])
const settings = ref<Record<string, string | number>>({})
const busy = ref(false)
const error = ref('')
let previous: { key: string, id: string } | undefined

const slot = computed(() => {
  const value = decorationSlots[slotKey.value]
  if (!value) throw new Error('未知的装扮部位：' + slotKey.value)
  return value
})
const uploadedUrls = computed(() => [...Object.values(images.value), ...items.value.map(item => item.url)])
const complete = computed(() => !!name.value && !!artist.value
  && slot.value.images.every(field => !!images.value[field.key])
  && (!slot.value.list || (items.value.length >= slot.value.list.min && items.value.every(item => !!item.name)))
  && slot.value.settings.every(setting => settings.value[setting.key] !== undefined && settings.value[setting.key] !== ''))

function ruleOf(rule: string): DecorationImageRule {
  const value = decorationRules[rule]
  if (!value) throw new Error('装扮规范缺少规则：' + rule)
  return value
}

function accept(rule: string) {
  return ruleOf(rule).formats.map(format => '.' + format).join(',')
}

function resetAssets() {
  images.value = {}
  items.value = []
  settings.value = Object.fromEntries(slot.value.settings.filter(setting => setting.type === 'color').map(setting => [setting.key, '#222222']))
  error.value = ''
}
resetAssets()

async function perform(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  try { await work() }
  catch (cause) { error.value = errorMessage(cause, '操作失败，请重试') }
  finally { busy.value = false; emit('busy', false) }
}

async function upload(file: File, asset: string, rule: string) {
  if (file.size > ruleOf(rule).maxKiB * 1024) throw new Error(`「${file.name}」超过 ${ruleOf(rule).maxKiB} KB`)
  const query = new URLSearchParams({ slot: slotKey.value, asset })
  const result = await uploadFile<{ url: string }>({ url: endpoint + '/images?' + query, file })
  if (result.code !== 200 || !result.data?.url) throw new Error(result.message || '图片上传失败')
  return result.data.url
}

async function uploadImage(event: Event, key: string, rule: string) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await perform(async () => { images.value[key] = await upload(file, key, rule) })
}

async function uploadItems(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  const list = slot.value.list
  if (!list || !files.length) return
  await perform(async () => {
    if (items.value.length + files.length > list.max) throw new Error(`${list.label}最多 ${list.max} 张`)
    for (const file of files) {
      const url = await upload(file, list.key, list.rule)
      items.value.push({ name: file.name.replace(/\.[^.]+$/, '').slice(0, list.nameMaxLength), url })
    }
  })
}

async function save() {
  let savedId: string | undefined
  await perform(async () => {
    const input = { slot: slotKey.value, name: name.value, artist: artist.value, images: { ...images.value },
      items: items.value.map(item => ({ ...item })), settings: { ...settings.value } }
    const key = JSON.stringify(input)
    // Retrying an unchanged draft reuses its id, so a lost response cannot create a duplicate artwork.
    const attempt = previous?.key === key ? previous : { key, id: spaceRequestId('artwork') }
    previous = attempt
    const result = await request.post(endpoint, { ...input, id: attempt.id })
    savedId = result.data
  })
  if (savedId) {
    emit('saved', savedId, name.value)
    name.value = ''
    resetAssets()
  }
}
</script>

<style scoped>
.artwork-editor { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
form { display: grid; align-content: start; gap: 12px; }
form p { margin: 0; color: var(--ej-muted); font-size: 13px; }
form a { color: var(--ej-accent); font-size: 13px; }
fieldset { display: grid; gap: 8px; margin: 0; padding: 12px; border: 1px solid var(--ej-line); border-radius: 12px; }
legend { padding: 0 4px; color: var(--ej-ink); font-size: 14px; }
.asset-preview { width: 72px; height: 72px; object-fit: contain; }
.item-list { display: grid; gap: 8px; margin: 0; padding-left: 20px; }
.item-list li { display: flex; align-items: center; gap: 8px; }
.item-list img { width: 40px; height: 40px; object-fit: contain; }
.item-list input { flex: 1; }
.image-preview { display: flex; flex-wrap: wrap; gap: 10px; padding: 16px; min-height: 120px; border: 1px solid var(--ej-line); border-radius: 16px; }
.image-preview img { width: 72px; height: 72px; object-fit: contain; }
button[type=submit] { justify-self: start; padding: 8px 16px; background: var(--studio-lime); color: var(--ej-on-color); border-radius: 20px; }
@media (max-width: 760px) { .artwork-editor { grid-template-columns: 1fr; } }
</style>
