const TICKET = /^[A-Za-z0-9_-]{43}$/
const DEPLOYMENT_ORIGIN = null
const WEB_ACCESS = { origins: ['http://*/*', 'https://*/*'] }
const CONTROL_GROUP_TITLE = '✦ EasyJob AI'
let active = null
let authorizing = false
let indicatorUpdate = Promise.resolve()
let lastCaptureAt = 0

function httpUrl(value) {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url : null
  } catch {
    return null
  }
}

function badge(text, title = '在 EasyJob 聊天页连接浏览器') {
  void chrome.action.setBadgeText({ text })
  void chrome.action.setTitle({ title })
}

function refreshControlIndicator() {
  indicatorUpdate = indicatorUpdate.then(async () => {
    const session = active
    const tab = session?.ready && Date.now() < session.expires
      ? usableTab(await getTab(session.tabId), session) : null
    const { controlGroup } = await chrome.storage.local.get('controlGroup')
    if (controlGroup) {
      const marked = await getTab(controlGroup.tabId)
      const group = marked?.groupId === controlGroup.groupId
        ? await chrome.tabGroups.get(controlGroup.groupId).catch(() => null) : null
      if (group?.title === CONTROL_GROUP_TITLE && group.color === 'purple') {
        if (active === session && tab?.id === marked.id && session.tabId === tab.id) return
        await chrome.tabs.ungroup(marked.id)
      }
      await chrome.storage.local.remove('controlGroup')
    }

    // Grouping a pinned or already grouped tab would change the user's layout.
    if (!tab || active !== session || session.tabId !== tab.id || tab.pinned ||
        tab.groupId !== chrome.tabGroups.TAB_GROUP_ID_NONE) return
    const groupId = await chrome.tabs.group({ tabIds: tab.id, createProperties: { windowId: tab.windowId } })
    try {
      await chrome.tabGroups.update(groupId, { title: CONTROL_GROUP_TITLE, color: 'purple' })
      await chrome.storage.local.set({ controlGroup: { tabId: tab.id, groupId } })
    } catch (error) {
      if ((await getTab(tab.id))?.groupId === groupId) await chrome.tabs.ungroup(tab.id)
      throw error
    }
  }).catch(error => console.warn('Could not update EasyJob control marker:', error.message))
}

refreshControlIndicator()

function stop(session, reason) {
  if (active !== session) return
  active = null
  refreshControlIndicator()
  session.socket.close()
  if (reason) badge('失败', reason)
  else badge('')
}

chrome.runtime.onMessageExternal.addListener((message, sender, reply) => {
  const site = httpUrl(sender.url)
  if ((sender.frameId !== undefined && sender.frameId !== 0) || !site || message?.type !== 'easyjob-browser-authorize' ||
      typeof message.ticket !== 'string' || !TICKET.test(message.ticket)) return
  if (DEPLOYMENT_ORIGIN ? site.origin !== DEPLOYMENT_ORIGIN :
      site.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(site.hostname)) return
  if (authorizing || sender.tab?.incognito) {
    reply({ accepted: false, reason: 'unavailable' })
    return
  }
  authorizing = true
  // Request synchronously within the message handler to preserve the Allow click's gesture.
  chrome.permissions.request(WEB_ACCESS).then(async granted => {
    if (!granted || !await chrome.permissions.contains(WEB_ACCESS)) {
      reply({ accepted: false, reason: 'denied' })
      return
    }
    if (active) stop(active)
    await connectBrowser(sender.tab, site.origin, message.ticket)
    reply({ accepted: true })
  }).catch(() => {
    reply({ accepted: false, reason: 'unavailable' })
  }).finally(() => { authorizing = false })
  return true
})

chrome.action.onClicked.addListener(() => {
  if (active) stop(active)
  else badge('', '请在 EasyJob 聊天页点击「连接浏览器」')
})

async function connectBrowser(tab, origin, ticket) {
  const endpoint = new URL('/api/agent/browser/ws', origin)
  endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:'
  const session = { socket: null, site: origin, tabId: null, origin: null, expires: Date.now() + 600000,
    documentId: null, shot: null, activation: 0, busy: false, receipts: new Map(), tabs: new Set() }
  const initial = (await chrome.tabs.query(Number.isInteger(tab?.windowId) ?
    { windowId: tab.windowId } : { currentWindow: true })).filter(item => usableTab(item, session))
    .sort((left, right) => (right.lastAccessed || 0) - (left.lastAccessed || 0))[0]
  if (initial) selectTab(session, initial)
  const socket = session.socket = new WebSocket(endpoint)
  active = session
  badge('连接', '正在连接 EasyJob')
  socket.onopen = async () => {
    const { visionEnabled } = await chrome.storage.local.get('visionEnabled')
    if (active === session) socket.send(JSON.stringify({
      type: 'hello', version: 1, ticket, vision: visionEnabled === true, multiTab: true,
    }))
  }
  socket.onclose = () => stop(session, session.ready ? undefined : '连接被拒绝或票据过期，请回 EasyJob 聊天页重新连接')
  socket.onerror = () => stop(session, '无法连接 EasyJob，请检查聊天页是否正常，再重新连接')
  socket.onmessage = event => { void receive(session, event.data) }
}

chrome.tabs.onRemoved.addListener(tabId => {
  active?.tabs.delete(tabId)
  if (active?.tabId === tabId) selectTab(active, null)
})
chrome.webNavigation.onCreatedNavigationTarget.addListener(({ sourceTabId, sourceFrameId, tabId }) => {
  if (sourceFrameId === 0 && active?.popup?.source === sourceTabId) active.popup.children.add(tabId)
})
chrome.tabs.onActivated.addListener(() => { if (active) active.activation++ })
chrome.windows.onFocusChanged.addListener(() => { if (active) active.activation++ })
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (active?.tabId === tabId && (info.url || info.status === 'loading')) {
    active.documentId = null
    active.shot = null
  }
  if (active?.tabId === tabId && (info.url || info.status === 'complete')) refreshControlIndicator()
})
chrome.permissions.onRemoved.addListener(() => {
  const session = active
  if (session) void chrome.permissions.contains(WEB_ACCESS).then(granted => {
    if (!granted) stop(session, '网页访问权限已撤销')
  })
})

async function receive(session, raw) {
  if (active !== session || Date.now() >= session.expires) { stop(session); return }
  try {
    const command = JSON.parse(raw)
    const send = value => {
      if (active === session && session.socket.readyState === WebSocket.OPEN) session.socket.send(JSON.stringify(value))
    }
    if (command.type === 'ready') {
      session.ready = true
      badge('ON', '浏览器会话已授权给 EasyJob，点击停止')
      refreshControlIndicator()
      return
    }
    if (command.type === 'heartbeat') { send({ type: 'heartbeat_ack' }); return }
    if (command.type !== 'action' || !TICKET.test(command.actionId) || session.busy ||
        !Number.isSafeInteger(command.deadlineMs)) { stop(session); return }
    if (session.receipts.has(command.actionId)) {
      send(session.receipts.get(command.actionId))
      return
    }
    session.busy = true
    let outcome
    try {
      outcome = command.deadlineMs > Date.now() ? await operate(session, command) : { status: 'expired' }
    } catch {
      outcome = { status: 'denied' }
    } finally {
      session.busy = false
      session.popup = null
    }
    const result = { type: 'result', actionId: command.actionId, ...outcome }
    if (!result.image) {
      if (session.receipts.size >= 16) session.receipts.delete(session.receipts.keys().next().value)
      session.receipts.set(command.actionId, result)
    }
    send(result)
  } catch {
    stop(session)
  }
}

function usableTab(tab, session) {
  const url = httpUrl(tab?.url)
  return tab && Number.isInteger(tab.id) && !tab.incognito && url && url.origin !== session.site ? tab : null
}

function selectTab(session, tab) {
  session.tabId = tab?.id ?? null
  session.origin = httpUrl(tab?.url)?.origin ?? null
  session.documentId = null
  session.shot = null
  if (active === session && session.ready) refreshControlIndicator()
}

async function getTab(id) {
  return Number.isInteger(id) ? chrome.tabs.get(id).catch(() => null) : null
}

async function observeTab(session, tabId, deadline) {
  while (active === session && Date.now() + 150 < deadline) {
    const tab = await getTab(tabId)
    if (!tab || session.tabId !== tabId) break
    if (tab.status === 'complete' && usableTab(tab, session)) {
      session.origin = httpUrl(tab.url).origin
      const result = await inject(session, { kind: 'observe' }, deadline)
      if (result.snapshot) {
        session.documentId = result.documentId
        return { status: 'ok', snapshot: { ...result.snapshot, tabId, documentId: result.documentId } }
      }
    }
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  return { status: 'tab_unavailable' }
}

async function operate(session, command) {
  const action = command.action
  if (active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
  if (action.kind === 'tabs') {
    const tabs = (await chrome.tabs.query({})).filter(tab => usableTab(tab, session)).slice(0, 24)
    session.tabs = new Set(tabs.map(tab => tab.id))
    return { status: 'ok', snapshot: { tabs: tabs.map(tab => ({
      id: tab.id, title: String(tab.title || '').slice(0, 100), origin: httpUrl(tab.url).origin,
      selected: tab.id === session.tabId,
    })) } }
  }
  if (action.kind === 'open' || action.kind === 'switch') {
    let tab
    if (action.kind === 'open') {
      const url = httpUrl(action.url)
      if (!url || url.origin === session.site) return { status: 'denied' }
      const parent = await getTab(session.tabId)
      if (active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
      tab = await chrome.tabs.create({ url: url.href, active: true,
        ...(parent ? { windowId: parent.windowId, openerTabId: parent.id } : {}) })
    } else {
      tab = session.tabs.has(action.tabId) && usableTab(await getTab(action.tabId), session)
      if (!tab || active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
      await chrome.tabs.update(tab.id, { active: true })
      if (active === session) await chrome.windows.update(tab.windowId, { focused: true })
    }
    selectTab(session, tab)
    return observeTab(session, tab.id, command.deadlineMs)
  }
  const current = usableTab(await getTab(session.tabId), session)
  if (!current) return { status: 'tab_unavailable' }
  const currentOrigin = httpUrl(current.url).origin
  if (currentOrigin !== session.origin) selectTab(session, current)
  if (action.kind === 'capture') {
    session.shot = null
    const { visionEnabled } = await chrome.storage.local.get('visionEnabled')
    if (!visionEnabled) return { status: 'denied' }
    if (active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
    if (!current.active) await chrome.tabs.update(current.id, { active: true })
    if (active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
    if (!(await chrome.windows.get(current.windowId)).focused) {
      await chrome.windows.update(current.windowId, { focused: true })
    }
    // Chrome limits captureVisibleTab calls across all sessions of an extension.
    const delay = Math.max(0, 550 - (Date.now() - lastCaptureAt))
    if (Date.now() + delay >= command.deadlineMs) return { status: 'expired' }
    if (delay) await new Promise(resolve => setTimeout(resolve, delay))
    if (active !== session || Date.now() >= command.deadlineMs) return { status: 'denied' }
    const activation = session.activation
    const before = await inject(session, { kind: 'viewport' }, command.deadlineMs)
    if (before.status !== 'ok' || before.sensitive) return { status: 'denied' }
    const tab = await chrome.tabs.get(session.tabId)
    if (!tab.active || !(await chrome.windows.get(tab.windowId)).focused || active !== session ||
        activation !== session.activation || Date.now() >= command.deadlineMs) return { status: 'denied' }
    lastCaptureAt = Date.now()
    const image = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 60 })
    const after = await inject(session, { kind: 'viewport' }, command.deadlineMs, before.documentId)
    const stillActive = (await chrome.tabs.get(session.tabId)).active
    if (!stillActive || activation !== session.activation || after.status !== 'ok' || after.sensitive ||
        before.signature !== after.signature || image.length > 790000) {
      return { status: 'stale_snapshot' }
    }
    const id = crypto.randomUUID()
    session.shot = { id, signature: before.signature, documentId: before.documentId }
    return { status: 'ok', image, shotId: id }
  }
  let visualAction = null
  if (action.kind === 'click_at') {
    const shot = session.shot
    session.shot = null
    const { visionEnabled } = await chrome.storage.local.get('visionEnabled')
    if (!visionEnabled || !shot || shot.id !== action.shotId) return { status: 'stale_snapshot' }
    visualAction = { ...action, signature: shot.signature }
    session.documentId = shot.documentId
  }
  session.shot = null
  if (!['observe', 'scroll', 'click', 'press', 'keypress', 'fill', 'click_at'].includes(action.kind)) return { status: 'denied' }
  const scoped = ['click', 'press', 'keypress', 'fill', 'click_at'].includes(action.kind)
  if (scoped && !session.documentId) return { status: 'stale_snapshot' }
  const sourceTab = session.tabId
  const canOpenTab = ['press', 'keypress', 'click_at'].includes(action.kind)
  if (canOpenTab) session.popup = { source: sourceTab, children: new Set() }
  const childrenBefore = canOpenTab ? new Set((await chrome.tabs.query({})).map(tab => tab.id)) : null
  let result = await inject(session, visualAction || action, command.deadlineMs, scoped ? session.documentId : null)
  if (result.status === 'stale_snapshot' && canOpenTab && session.documentId) {
    const refreshed = await inject(session, { kind: 'observe' }, command.deadlineMs, session.documentId)
    if (refreshed.snapshot) result = { ...refreshed, status: 'stale_snapshot' }
  }
  if (result.status === 'clicked') {
    const popupDeadline = Math.min(command.deadlineMs - 200, Date.now() + 2200)
    while (active === session && Date.now() < popupDeadline) {
      const children = (await chrome.tabs.query({})).filter(tab =>
        (session.popup.children.has(tab.id) || tab.openerTabId === sourceTab) &&
        !tab.incognito && !childrenBefore.has(tab.id))
      if (children.length === 1) {
        const child = children[0]
        selectTab(session, child)
        const observed = await observeTab(session, child.id, command.deadlineMs)
        if (observed.status === 'ok') return { ...observed, status: 'opened_tab' }
        return { status: 'clicked' }
      }
      if (children.length > 1) return { status: 'multiple_tabs' }
      await new Promise(resolve => setTimeout(resolve, 150))
    }
    const observed = await observeTab(session, sourceTab, command.deadlineMs)
    return observed.status === 'ok' ? observed : { status: 'clicked' }
  }
  if (result.status === 'navigating') {
    const before = result.documentId
    let nextDocument = false
    while (active === session && Date.now() + 350 < command.deadlineMs) {
      await new Promise(resolve => setTimeout(resolve, 200))
      const tab = await chrome.tabs.get(session.tabId)
      if (tab.status === 'complete') {
        if (!usableTab(tab, session)) return { status: 'denied' }
        session.origin = httpUrl(tab.url).origin
        result = await inject(session, { kind: 'observe' }, command.deadlineMs)
        if (result.status === 'ok' && result.documentId !== before) { nextDocument = true; break }
      }
    }
    if (!nextDocument) return { status: 'stale_snapshot' }
  }
  if (result.snapshot) session.documentId = result.documentId
  const { documentId, ...outcome } = result
  return outcome.snapshot ? { ...outcome, snapshot: { ...outcome.snapshot, tabId: sourceTab, documentId } } : outcome
}

async function inject(session, action, deadline, documentId = null) {
  if (active !== session || Date.now() >= deadline) return { status: 'denied' }
  try {
    const [entry] = await chrome.scripting.executeScript({
      target: { tabId: session.tabId, ...(documentId ? { documentIds: [documentId] } : { frameIds: [0] }) },
      func: pageAction, args: [session.origin, action, deadline],
    })
    return { ...entry.result, documentId: entry.documentId }
  } catch {
    return { status: documentId ? 'stale_snapshot' : 'denied' }
  }
}

async function pageAction(origin, action, deadline) {
  if (location.origin !== origin || Date.now() >= deadline || document.prerendering) return { status: 'denied' }
  const excluded = 'script,style,noscript,template,input,textarea,select,option,[contenteditable],[role="textbox"],[aria-hidden="true"],[hidden]'
  const sensitive = /password|passcode|passwd|otp|token|secret|pin\b|card.?number|cvv|cvc|验证码|密码|密钥|卡号/i
  const compact = (value, length) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, length)
  const onScreen = rect => rect.width > 0 && rect.height > 0 && rect.bottom > 0 &&
    rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth
  const roots = [document]
  for (let i = 0; i < roots.length && roots.length < 128; i++) {
    for (const node of roots[i].querySelectorAll('*')) {
      if (node.shadowRoot && roots.length < 128) roots.push(node.shadowRoot)
    }
  }
  const queryAll = selector => roots.flatMap(root => Array.from(root.querySelectorAll(selector)))
  function deepHit(x, y) {
    let node = document.elementFromPoint(x, y)
    while (node?.shadowRoot) {
      const inner = node.shadowRoot.elementFromPoint(x, y)
      if (!inner || inner === node) break
      node = inner
    }
    return node
  }
  function blockedAncestor(node) {
    while (node) {
      if (node.closest('[inert],[hidden],[aria-hidden="true"],[aria-disabled="true"],:disabled')) return true
      node = node.getRootNode().host
    }
    return false
  }
  function visible(node) {
    const rect = node.getBoundingClientRect()
    const css = getComputedStyle(node)
    return onScreen(rect) && css.visibility === 'visible' && css.opacity !== '0' &&
      !blockedAncestor(node)
  }
  function linkUrl(node) {
    try {
      if (!visible(node) || node.hasAttribute('download')) return null
      const url = new URL(node.href)
      return url.origin === origin && !url.username && !url.password && !url.search &&
        !/(?:^|\/)(?:logout|signout|delete|remove|unsubscribe|purchase|checkout)(?:\/|$)/i.test(url.pathname)
        ? url : null
    } catch { return null }
  }
  function fieldDetails(node) {
    if (!visible(node) || node.matches(':disabled,[readonly],[contenteditable]') || node.closest(dropdownSelector)) return null
    if (node.form?.querySelector('input[type="password"],input[autocomplete^="cc-"],input[autocomplete="one-time-code"]')) return null
    if (!['text', 'search', 'email', 'tel', 'url', 'number', 'textarea', 'select-one',
      'checkbox', 'radio', 'date', 'month', 'week', 'time', 'datetime-local'].includes(node.type)) return null
    const labels = Array.from(node.labels || [], label => {
      const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT)
      const text = []
      while (walker.nextNode()) {
        const item = walker.currentNode
        if (!item.parentElement?.closest(excluded)) text.push(item.data)
      }
      return text.join(' ')
    })
    const labelledBy = (node.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map(id => node.getRootNode().getElementById(id)?.innerText).filter(Boolean).join(' ')
    const label = compact(node.getAttribute('aria-label') || labelledBy || labels.join(' ').trim() ||
      node.placeholder || node.name, 100)
    if (!label || sensitive.test([label, node.name, node.id, node.autocomplete, node.placeholder].join(' ')) ||
        /cc-|one-time-code|current-password|new-password/i.test(node.autocomplete || '')) return null
    const options = node instanceof HTMLSelectElement ? Array.from(node.options).slice(0, 20)
      .filter(option => !option.disabled && !option.parentElement?.matches('optgroup[disabled]'))
      .map(option => compact(option.label, 60)) : undefined
    const choice = node.type === 'radio' || node.type === 'checkbox'
    const group = choice && node.closest('fieldset')?.querySelector('legend')
    return { label, type: node.type, required: node.required, options,
      checked: choice ? node.checked : undefined,
      group: group ? compact(group.innerText, 100) : undefined }
  }
  const dropdownSelector = '[role="combobox"],[aria-haspopup="listbox"],.el-select,.ant-select,.arco-select,.n-base-selection'
  const optionSelector = '[role="option"],.el-select-dropdown__item,.ant-select-item-option,.arco-select-option,.n-base-select-option'
  const choiceSelector = '[role="radio"],[role="checkbox"],[role="switch"]'
  const localControlTypes = ['combobox', 'option', 'radio', 'checkbox', 'switch']
  const buttonSelector = `button,input[type="submit"],input[type="button"],[role="button"]:not(a),${dropdownSelector},${choiceSelector}`
  function hitTarget(node) {
    const rect = node.getBoundingClientRect()
    const hit = deepHit(rect.x + rect.width / 2, rect.y + rect.height / 2)
    return node.contains(hit) ? hit : null
  }
  function buttonDetails(node) {
    if (!visible(node) || node.matches(':disabled') || node.type === 'reset' ||
        node.closest('a,[aria-disabled="true"],.is-disabled,.ant-select-item-option-disabled,.ant-select-disabled,.arco-select-option-disabled,.n-base-select-option--disabled')) return null
    const option = node.matches(optionSelector)
    const dropdown = node.matches(dropdownSelector)
    const choice = node.matches(choiceSelector)
    if (choice && (node.matches('input') || node.querySelector('input[type="checkbox"],input[type="radio"]'))) return null
    if (dropdown && node.querySelector('[role="combobox"]')) return null
    const labelledBy = (node.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map(id => document.getElementById(id)?.textContent || '').join(' ').trim()
    // Some icon-only controls expose their purpose only in a CSS class.
    const sendIcon = node instanceof HTMLButtonElement && node.querySelector('svg') &&
      Array.from(node.classList).some(name => /(?:^|[-_])(?:send|submit)(?:[-_](?:btn|button|icon))?$/i.test(name))
    const placeholder = dropdown && (node.getAttribute('placeholder') ||
      node.querySelector('input[placeholder]')?.getAttribute('placeholder') ||
      node.querySelector('.el-select__placeholder,.ant-select-selection-placeholder,.arco-select-view-input,.n-base-selection-placeholder')?.innerText)
    const fieldLabel = dropdown && node.closest('.el-form-item')?.querySelector('.el-form-item__label')?.innerText
    const label = compact(node.getAttribute('aria-label') || labelledBy || fieldLabel || placeholder || node.title ||
      node.innerText || node.value || node.querySelector('svg title')?.textContent ||
      node.querySelector('img[alt]')?.alt || node.getAttribute('data-testid') || (sendIcon ? '发送' : ''), 100)
    if (!label && node.type !== 'submit' && !node.matches('button,[role="button"]')) return null
    const form = node.form || node.closest('form')
    if (form?.querySelector('input[type="password"],input[autocomplete^="cc-"],input[autocomplete="one-time-code"]')) return null
    const localChoice = option || dropdown || choice
    // A file picker elsewhere in a form does not make selecting a field an upload.
    if (form?.querySelector('input[type="file"]') &&
        (!localChoice || (node.form === form && node.type === 'submit'))) return null
    const destination = node.getAttribute('formaction') || form?.getAttribute('action')
    if (destination) {
      try { if (new URL(destination, location.href).origin !== origin) return null }
      catch { return null }
    }
    const target = (node.getAttribute('formtarget') || form?.target || '').toLowerCase()
    if (target && !['_self', '_blank'].includes(target)) return null
    const menu = option ? node.closest('[role="listbox"]') : null
    if ((option || dropdown || choice) && sensitive.test([label, node.id, node.getAttribute('name'),
      menu?.getAttribute('aria-label')].join(' '))) return null
    const caret = dropdown && node.closest('.el-select')?.querySelector('.el-select__caret')
    const elementMenu = option && node.closest('.el-select-dropdown')
    const expanded = dropdown ? node.getAttribute('aria-expanded') ??
      (caret ? String(caret.classList.contains('is-reverse')) : undefined) : undefined
    return { label: label || (node.type === 'submit' ? '提交表单' : '未命名图标按钮'), type: option ? 'option' : dropdown ? 'combobox' :
      choice ? node.getAttribute('role') : node.type || 'button',
      expanded,
      selected: option ? node.getAttribute('aria-selected') ??
        (node.matches('.el-select-dropdown__item') ? String(node.classList.contains('selected')) : undefined) : undefined,
      singleSelect: option && (elementMenu ? !elementMenu.classList.contains('is-multiple') :
        Boolean(menu && menu.getAttribute('aria-multiselectable') !== 'true')),
      checked: choice ? node.getAttribute('aria-checked') : undefined,
      destination: destination || '', target, method: node.getAttribute('formmethod') || form?.method || '' }
  }
  function formState(node) {
    const form = node.form || node.closest('form')
    const inputs = form ? Array.from(form.elements) :
      queryAll('input,textarea,select,[contenteditable="true"]').filter(visible)
    return inputs.map(field => [field, field.value ?? field.textContent, field.checked])
  }
  function snapshot() {
    const nodes = new Map(), links = [], fields = [], buttons = []
    for (const node of queryAll('a[href]')) {
      if (links.length >= 18) break
      const url = linkUrl(node)
      const label = compact(node.innerText || node.getAttribute('aria-label'), 90)
      if (!url || !label) continue
      const id = 'l' + links.length
      nodes.set(id, { node, href: url.href, label })
      links.push({ id, label, path: url.pathname + url.hash })
    }
    for (const node of queryAll('input,textarea,select')) {
      if (fields.length >= 12) break
      const field = fieldDetails(node)
      if (!field) continue
      const id = 'f' + fields.length
      nodes.set(id, { node, field: JSON.stringify(field) })
      fields.push({ id, ...field })
    }
    // Open menu options can appear after the rest of the form in a portal.
    const candidates = new Set([...queryAll(optionSelector), ...queryAll(buttonSelector)])
    for (const node of candidates) {
      if (buttons.length >= 18) break
      const details = buttonDetails(node)
      if (!details || (details.type === 'option' && !hitTarget(node))) continue
      const id = 'b' + buttons.length
      const localControl = localControlTypes.includes(details.type) && !(node.form && node.type === 'submit')
      nodes.set(id, { node, button: JSON.stringify(details), form: localControl ? null : formState(node) })
      const { label, type, expanded, selected, checked } = details
      buttons.push({ id, label, type, expanded, selected, checked })
    }
    const text = []
    const root = document.querySelector('main,[role="main"]') || document.body
    if (!root) return { status: 'denied' }
    const range = document.createRange()
    let length = 0, visited = 0
    for (const textRoot of [root, ...roots.slice(1)]) {
      const walker = document.createTreeWalker(textRoot, NodeFilter.SHOW_TEXT)
      for (let item; visited < 800 && length < 4200 && (item = walker.nextNode()); visited++) {
        const parent = item.parentElement
        if (!parent || parent.closest(excluded) || !visible(parent)) continue
        range.selectNodeContents(item)
        if (!onScreen(range.getBoundingClientRect())) continue
        const value = compact(item.data, 4200 - length)
        if (value) { text.push(value); length += value.length + 1 }
      }
    }
    const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
    globalThis.easyJobBrowserSnapshot = { id, href: location.href, nodes }
    return { status: 'ok', snapshot: { id, origin, path: location.pathname + location.hash,
      title: compact(document.title, 120), links, fields, buttons, text: text.join('\n') } }
  }
  function viewport() {
    // Compare layout and visible content, not only viewport size. A menu can
    // replace a button without scrolling while the visual model is running.
    const layout = queryAll('*').filter(visible).map(node => {
      const rect = node.getBoundingClientRect()
      return [node.tagName, rect.x, rect.y, rect.width, rect.height,
        node.getAttribute('role'), node.getAttribute('aria-expanded'), node.getAttribute('aria-selected'),
        node.getAttribute('aria-label'), node.getAttribute('href'), node.value, node.checked,
        Array.from(node.childNodes).filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join('')]
    })
    return {
      sensitive: queryAll('iframe,input[type="password"],input[autocomplete^="cc-"],input[autocomplete="one-time-code"]').length > 0,
      signature: JSON.stringify([location.href, innerWidth, innerHeight, scrollX, scrollY, layout]) }
  }
  if (action.kind === 'observe') return snapshot()
  if (action.kind === 'scroll') {
    if (!Number.isInteger(action.dy) || Math.abs(action.dy) > 1600) return { status: 'denied' }
    const before = scrollY
    scrollBy({ top: action.dy, behavior: 'instant' })
    return before === scrollY ? { status: 'no_change' } : snapshot()
  }
  if (action.kind === 'viewport') return { status: 'ok', ...viewport() }
  if (action.kind === 'click_at') {
    const view = viewport()
    if (view.sensitive) return { status: 'denied' }
    if (action.signature !== view.signature || ![action.x, action.y].every(n => Number.isFinite(n) && n >= 0 && n < 1)) {
      return { status: 'stale_snapshot' }
    }
    const x = action.x * innerWidth, y = action.y * innerHeight
    const hit = deepHit(x, y)
    if (!hit || !visible(hit) || blockedAncestor(hit) || hit.closest('input[type="file"],a[download]')) return { status: 'denied' }
    const link = hit.closest('a[href]')
    if (link) {
      try {
        const url = new URL(link.href, location.href)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return { status: 'denied' }
      } catch { return { status: 'denied' } }
    }
    globalThis.easyJobBrowserSnapshot = null
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) {
      const EventType = type.startsWith('pointer') ? PointerEvent : MouseEvent
      hit.dispatchEvent(new EventType(type, { bubbles: true, composed: true, clientX: x, clientY: y, button: 0, pointerType: 'mouse' }))
    }
    // Preserve coordinates for canvas/custom widgets. Dispatching click also
    // invokes native button/link activation (including submit and target=_blank).
    hit.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, composed: true,
      clientX: x, clientY: y, button: 0 }))
    return { status: 'clicked' }
  }
  const saved = globalThis.easyJobBrowserSnapshot
  if (!saved || saved.id !== action.snapshotId || saved.href !== location.href) return { status: 'stale_snapshot' }
  if (action.kind === 'keypress') {
    const entry = saved.nodes.get(action.elementId)
    const node = entry?.node
    const codes = { Enter: 13, Escape: 27, ArrowUp: 38, ArrowDown: 40 }
    if (!Object.hasOwn(codes, action.key)) return { status: 'denied' }
    if (!node?.isConnected || !visible(node) || !hitTarget(node)) return { status: 'stale_snapshot' }
    const details = entry.field ? fieldDetails(node) : entry.button ? buttonDetails(node) : null
    if (!details || JSON.stringify(details) !== (entry.field || entry.button)) return { status: 'stale_snapshot' }
    // Restrict keyboard interaction to observed controls. Synthetic keys reach
    // framework listeners but are not trusted OS input; always observe the result.
    const form = node.form || node.closest('form')
    if (form?.querySelector('input[type="file"],input[type="password"],input[autocomplete^="cc-"],input[autocomplete="one-time-code"]')) return { status: 'denied' }
    if (form?.action && new URL(form.action, location.href).origin !== origin) return { status: 'denied' }
    if (entry.form) {
      const current = formState(node)
      if (current.length !== entry.form.length || current.some((row, i) => row.some((value, j) => value !== entry.form[i][j]))) return { status: 'stale_snapshot' }
    }
    node.focus()
    globalThis.easyJobBrowserSnapshot = null
    const init = { key: action.key, code: action.key, keyCode: codes[action.key], which: codes[action.key],
      bubbles: true, cancelable: true, composed: true }
    node.dispatchEvent(new KeyboardEvent('keydown', init))
    node.dispatchEvent(new KeyboardEvent('keyup', init))
    return { status: 'clicked' }
  }
  if (action.kind === 'click') {
    const entry = saved.nodes.get(action.elementId)
    const url = entry?.node instanceof HTMLAnchorElement && linkUrl(entry.node)
    if (!url || url.href !== entry.href || compact(entry.node.innerText || entry.node.getAttribute('aria-label'), 90) !== entry.label) {
      return { status: 'stale_snapshot' }
    }
    if (url.pathname === location.pathname && url.search === location.search) {
      location.hash = url.hash
      return snapshot()
    }
    setTimeout(() => { if (Date.now() < deadline && location.href === saved.href) location.assign(url.href) }, 0)
    return { status: 'navigating' }
  }
  if (action.kind === 'press') {
    const entry = saved.nodes.get(action.elementId)
    const node = entry?.node
    const details = node?.isConnected && buttonDetails(node)
    if (!details || !entry.button) return { status: 'stale_snapshot' }
    const prior = JSON.parse(entry.button)
    if (!entry.form && details.type === 'combobox' && details.expanded === 'true' &&
        prior.type === details.type && prior.label === details.label) {
      return { ...snapshot(), status: 'dropdown_already_open' }
    }
    if (JSON.stringify(details) !== entry.button) {
      return { status: 'stale_snapshot' }
    }
    if (!entry.form && details.singleSelect && details.selected === 'true') {
      return { ...snapshot(), status: 'option_already_selected' }
    }
    if (entry.form) {
      const current = formState(node)
      if (current.length !== entry.form.length ||
          current.some((row, index) => row.some((value, i) => value !== entry.form[index][i]))) {
        return { status: 'stale_snapshot' }
      }
    }
    const hit = hitTarget(node)
    if (!hit) return { status: 'stale_snapshot' }
    globalThis.easyJobBrowserSnapshot = null
    if (!entry.form && localControlTypes.includes(details.type)) {
      hit.click()
      await new Promise(resolve => setTimeout(resolve, 100))
      if (details.type === 'combobox') {
        const until = Math.min(Date.now() + 500, deadline - 50)
        while (Date.now() < until &&
            !queryAll(optionSelector).some(e => visible(e) && hitTarget(e))) {
          await new Promise(resolve => setTimeout(resolve, 50))
        }
      }
      if (Date.now() >= deadline) return { status: 'clicked' }
      return snapshot()
    }
    node.click()
    return { status: 'clicked' }
  }
  if (action.kind !== 'fill' || !Array.isArray(action.fields) || action.fields.length < 1 || action.fields.length > 6 ||
      new Set(action.fields.map(item => item.elementId)).size !== action.fields.length) return { status: 'denied' }
  const writes = []
  for (const item of action.fields) {
    const entry = saved.nodes.get(item.elementId)
    const node = entry?.node
    if (!node?.isConnected || !entry.field || JSON.stringify(fieldDetails(node)) !== entry.field ||
        typeof item.text !== 'string' || item.text.length > 500) return { status: 'stale_snapshot' }
    let value = item.text
    const choice = node.type === 'radio' || node.type === 'checkbox'
    if (choice) {
      if (!['true', 'false'].includes(value) || (node.type === 'radio' && value !== 'true')) return { status: 'denied' }
      value = value === 'true'
      if (node.type === 'radio' && node.name && writes.some(write =>
        write.node.type === 'radio' && write.node.name === node.name && write.node.form === node.form)) {
        return { status: 'denied' }
      }
    } else if (node instanceof HTMLSelectElement) {
      const options = Array.from(node.options).slice(0, 20).filter(option => !option.disabled &&
        !option.parentElement?.matches('optgroup[disabled]') && compact(option.label, 60) === value)
      if (options.length !== 1) return { status: 'stale_snapshot' }
      value = options[0].value
    } else if (['date', 'month', 'week', 'time', 'datetime-local'].includes(node.type)) {
      const test = node.cloneNode(false)
      test.value = value
      if (test.value !== value || test.validity.rangeUnderflow || test.validity.rangeOverflow ||
          test.validity.stepMismatch || test.validity.valueMissing) return { status: 'denied' }
    } else if ((node.maxLength >= 0 && value.length > node.maxLength) ||
        (node.type === 'number' && value && !Number.isFinite(Number(value)))) return { status: 'denied' }
    writes.push({ node, value, choice, field: entry.field })
  }
  for (const { node, value, choice, field } of writes) {
    if (!node.isConnected || JSON.stringify(fieldDetails(node)) !== field) return { status: 'partial' }
    if (choice) {
      if (node.checked !== value) {
        const rect = node.getBoundingClientRect()
        if (deepHit(rect.x + rect.width / 2, rect.y + rect.height / 2) !== node) return { status: 'partial' }
        node.click()
      }
      if (node.checked !== value) return { status: 'partial' }
      continue
    }
    if (node.value === value) continue
    const prototype = node instanceof HTMLSelectElement ? HTMLSelectElement.prototype :
      node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, value)
    node.dispatchEvent(new Event('input', { bubbles: true, composed: true }))
    node.dispatchEvent(new Event('change', { bubbles: true, composed: true }))
    if (node.value !== value) return { status: 'partial' }
  }
  await new Promise(resolve => setTimeout(resolve, 120))
  if (writes.some(({ node, value, choice }) => !node.isConnected ||
      (choice ? node.checked : node.value) !== value)) return { status: 'partial' }
  globalThis.easyJobBrowserSnapshot = null
  return snapshot()
}
