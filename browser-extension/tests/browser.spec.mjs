import assert from 'node:assert/strict'
import { before, after, beforeEach, test } from 'node:test'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { spawn } from 'node:child_process'
import { readFile, writeFile, mkdir, mkdtemp, copyFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(join(root, 'frontend/package.json'))
const { chromium } = require('playwright')
let server, context, worker, page, origin, artifacts

const html = `<!doctype html><meta charset="utf-8"><title>浏览器适配验收</title>
<style>body{font:20px sans-serif;padding:30px}button,input,textarea,.choice{font:inherit;padding:15px;margin:10px}#menu[hidden]{display:none}.choice{cursor:pointer;background:#ddd;width:200px}canvas{border:1px solid}#shadow{display:block;margin:20px}</style>
<label>姓名<input id="name" aria-label="姓名"></label>
<button id="dropdown">民族</button><div id="menu" hidden><div class="choice" id="han">汉族</div></div>
<p id="chosen">尚未选择</p><p id="input-state">尚未填写</p>
<form action="/chat" target="_blank"><textarea name="question" aria-label="问题"></textarea><button id="send">发送</button></form>
<button id="disabled" disabled>不可点击</button>
<button type="button" id="icon-only"><svg width="10" height="10"><path d="M0 5 L10 5"/></svg></button>
<div id="shadow"></div><canvas width="150" height="60"></canvas>
<script>
document.querySelector('#dropdown').onclick=()=>{document.querySelector('#menu').hidden=!document.querySelector('#menu').hidden};
document.querySelector('#han').onclick=()=>{document.querySelector('#chosen').textContent='已选择汉族';document.querySelector('#menu').hidden=true};
document.querySelector('#name').oninput=e=>document.querySelector('#input-state').textContent='已填写'+e.target.value;
document.querySelector('textarea').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();window.open('/chat','_blank')}};
document.querySelector('canvas').onclick=e=>{const r=e.target.getBoundingClientRect();
if(e.clientX>r.x&&e.clientX<r.right&&e.clientY>r.y&&e.clientY<r.bottom)document.querySelector('#chosen').textContent='画布已点击'};
const shadow=document.querySelector('#shadow').attachShadow({mode:'open'});
shadow.innerHTML='<style>input,button{font:20px sans-serif;padding:12px}</style><input aria-label="影子输入"><button>影子按钮</button><p>等待操作</p>';
shadow.querySelector('input').oninput=e=>shadow.querySelector('p').textContent=e.target.value;
shadow.querySelector('button').onclick=()=>shadow.querySelector('p').textContent='影子按钮已点击';
</script>`

before(async () => {
  await mkdir(join(root, 'temp'), { recursive: true })
  artifacts = await mkdtemp(join(root, 'temp/browser-acceptance-'))
  const extension = join(artifacts, 'extension')
  await mkdir(extension)
  for (const file of ['worker.js', 'options.js', 'options.html']) {
    await copyFile(join(root, 'browser-extension', file), join(extension, file))
  }
  const manifest = JSON.parse(await readFile(join(root, 'browser-extension/manifest.json'), 'utf8'))
  // Isolated test profile only: pregrant capture permission, without touching
  // the user's extension/profile or the production authorization manifest.
  manifest.host_permissions = ['<all_urls>']
  await writeFile(join(extension, 'manifest.json'), JSON.stringify(manifest))
  server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8')
    res.end(req.url.startsWith('/chat') ? '<title>对话页</title><main>问题已收到</main>' : html)
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  origin = `http://127.0.0.1:${server.address().port}`
  context = await chromium.launchPersistentContext(join(artifacts, 'profile'), {
    channel: 'chromium', headless: true, viewport: { width: 1200, height: 1100 },
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
  })
  worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker')
  await worker.evaluate(() => chrome.storage.local.set({ visionEnabled: true }))
})

beforeEach(async () => {
  for (const old of context.pages()) await old.close()
  page = await context.newPage()
  await page.goto(origin)
  await worker.evaluate(async origin => {
    const tab = (await chrome.tabs.query({})).find(tab => tab.url === origin + '/')
    active = { site: 'https://easyjob.test', tabId: tab.id, origin, documentId: null,
      shot: null, activation: 0, ready: false, expires: Date.now() + 60000, tabs: new Set() }
  }, origin)
})

after(async () => {
  await context?.close()
  if (server) await new Promise(resolve => server.close(resolve))
})

async function action(value) {
  return worker.evaluate(action => operate(active, { action, deadlineMs: Date.now() + 8000 }), value)
}
async function point(selector) {
  const box = await page.locator(selector).boundingBox()
  assert.ok(box)
  const view = page.viewportSize()
  return { x: (box.x + box.width / 2) / view.width, y: (box.y + box.height / 2) / view.height }
}
async function visual(selector) {
  const shot = await action({ kind: 'capture' })
  assert.equal(shot.status, 'ok')
  assert.match(shot.image, /^data:image\/jpeg;base64,/)
  return action({ kind: 'click_at', shotId: shot.shotId, ...await point(selector) })
}

test('keyboard Enter sends from an observed input and follows its new tab', async () => {
  const observed = await action({ kind: 'observe' })
  assert.ok(observed.snapshot.buttons.some(button => button.label === '未命名图标按钮'))
  const field = observed.snapshot.fields.find(field => field.label === '问题')
  const filled = await action({ kind: 'fill', snapshotId: observed.snapshot.id,
    fields: [{ elementId: field.id, text: '杭州最近天气' }] })
  const denied = await action({ kind: 'keypress', snapshotId: filled.snapshot.id, elementId: field.id, key: 'F12' })
  assert.equal(denied.status, 'denied')
  const stale = await action({ kind: 'keypress', snapshotId: 'old', elementId: field.id, key: 'Enter' })
  assert.equal(stale.status, 'stale_snapshot')
  const current = await action({ kind: 'observe' })
  const sent = await action({ kind: 'keypress', snapshotId: current.snapshot.id, elementId: field.id, key: 'Enter' })
  assert.equal(sent.status, 'opened_tab')
  assert.match(sent.snapshot.text, /问题已收到/)
})

test('visual fallback selects a custom option absent from DOM button inventory', async () => {
  const observed = await action({ kind: 'observe' })
  const button = observed.snapshot.buttons.find(button => button.label === '民族')
  const opened = await action({ kind: 'press', snapshotId: observed.snapshot.id, elementId: button.id })
  assert.equal(opened.status, 'ok')
  assert.equal(opened.snapshot.buttons.some(button => button.label === '汉族'), false)
  const selected = await visual('#han')
  assert.equal(selected.status, 'ok')
  assert.match(selected.snapshot.text, /已选择汉族/)
  assert.equal(await page.locator('#menu').isVisible(), false)
})

test('visual submit follows target=_blank and reads back the new tab', async () => {
  const observed = await action({ kind: 'observe' })
  const field = observed.snapshot.fields.find(field => field.label === '问题')
  const filled = await action({ kind: 'fill', snapshotId: observed.snapshot.id,
    fields: [{ elementId: field.id, text: '测试问题' }] })
  assert.equal(filled.status, 'ok')
  const sent = await visual('#send')
  assert.equal(sent.status, 'opened_tab')
  assert.match(sent.snapshot.text, /问题已收到/)
  const tab = context.pages().find(tab => tab.url().includes('/chat?'))
  assert.equal(new URL(tab.url()).searchParams.get('question'), '测试问题')
  assert.notEqual(sent.snapshot.tabId, observed.snapshot.tabId)
})

test('open shadow DOM controls can be filled and visually clicked', async () => {
  const observed = await action({ kind: 'observe' })
  const field = observed.snapshot.fields.find(field => field.label === '影子输入')
  assert.ok(field)
  const filled = await action({ kind: 'fill', snapshotId: observed.snapshot.id,
    fields: [{ elementId: field.id, text: '框架状态已更新' }] })
  assert.equal(filled.status, 'ok')
  assert.equal(await page.locator('#shadow p').textContent(), '框架状态已更新')
  const clicked = await visual('#shadow button')
  assert.equal(clicked.status, 'ok')
  assert.equal(await page.locator('#shadow p').textContent(), '影子按钮已点击')
  assert.match(clicked.snapshot.text, /影子按钮已点击/)
})

test('a changed target invalidates the screenshot and never clicks its replacement', async () => {
  const shot = await action({ kind: 'capture' })
  assert.equal(shot.status, 'ok')
  const coordinate = await point('#dropdown')
  await page.locator('#dropdown').evaluate(node => { node.textContent = '替换后的危险操作' })
  const result = await action({ kind: 'click_at', shotId: shot.shotId, ...coordinate })
  assert.equal(result.status, 'stale_snapshot')
  assert.equal(await page.locator('#menu').isVisible(), false)
})

test('disabled controls are not activated and screenshot handles are single use', async () => {
  const shot = await action({ kind: 'capture' })
  const result = await action({ kind: 'click_at', shotId: shot.shotId, ...await point('#disabled') })
  assert.equal(result.status, 'denied')
  const repeat = await action({ kind: 'click_at', shotId: shot.shotId, ...await point('#dropdown') })
  assert.equal(repeat.status, 'stale_snapshot')
})

test('sensitive fields block screenshots even inside open shadow DOM', async () => {
  await page.locator('#shadow input').evaluate(node => { node.type = 'password' })
  assert.equal((await action({ kind: 'capture' })).status, 'denied')
})

test('canvas clicks still work and return an updated observation', async () => {
  const clicked = await visual('canvas')
  assert.equal(clicked.status, 'ok')
  assert.match(clicked.snapshot.text, /画布已点击/)
})

test('ordinary page screenshot is available for a real visual-model smoke test', async () => {
  const shot = await action({ kind: 'capture' })
  assert.equal(shot.status, 'ok')
  const target = await point('#dropdown')
  await writeFile(join(root, 'temp/browser-vision-fixture.json'), JSON.stringify({
    image: shot.image, target, width: 1200, height: 1100,
  }))
})

test('live model locates a dropdown, chooses its option, and submits into a new tab', {
  skip: process.env.EASYJOB_BROWSER_LIVE_VISION !== '1', timeout: 90000,
}, async () => {
  async function modelClick(target) {
    const shot = await action({ kind: 'capture' })
    assert.equal(shot.status, 'ok')
    const point = await new Promise((resolve, reject) => {
      const python = spawn(join(root, 'services/python-agent/.venv/Scripts/python.exe'),
        [join(root, 'browser-extension/tests/locate.py')], {
          cwd: join(root, 'services/python-agent'), windowsHide: true,
          env: { ...process.env, EASYJOB_TRACING_ENABLED: 'false', PYTHONPATH: '.' },
        })
      let output = ''
      python.stdout.on('data', data => { output += data })
      python.on('error', reject)
      python.on('close', code => {
        if (code) return reject(new Error(`Visual model probe failed (${code})`))
        try { resolve(JSON.parse(output)) } catch { reject(new Error('Invalid visual-model result')) }
      })
      python.stdin.end(JSON.stringify({ image: shot.image, target }))
    })
    assert.ok(point, 'the live model must return a point')
    return action({ kind: 'click_at', shotId: shot.shotId, ...point })
  }
  assert.equal((await modelClick('点击页面上方写着“民族”的按钮')).status, 'ok')
  assert.equal(await page.locator('#menu').isVisible(), true)
  assert.equal((await modelClick('点击已经展开的民族菜单里的“汉族”选项')).status, 'ok')
  assert.equal(await page.locator('#chosen').textContent(), '已选择汉族')
  const observed = await action({ kind: 'observe' })
  const field = observed.snapshot.fields.find(field => field.label === '问题')
  await action({ kind: 'fill', snapshotId: observed.snapshot.id, fields: [{ elementId: field.id, text: '视觉链路验收' }] })
  const result = await modelClick('点击问题输入框右边的“发送”按钮')
  assert.equal(result.status, 'opened_tab')
  assert.match(result.snapshot.text, /问题已收到/)
  await writeFile(join(root, 'temp/browser-live-vision-result.json'), JSON.stringify({
    dropdownOpened: true, optionSelected: true, followedNewTab: true, resultReadBack: true,
  }, null, 2))
})
