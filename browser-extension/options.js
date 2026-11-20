const button = document.querySelector('#vision')
const status = document.querySelector('#status')
async function update() {
  const { visionEnabled } = await chrome.storage.local.get('visionEnabled')
  button.textContent = visionEnabled ? '关闭视觉操作' : '启用视觉操作'
}

button.addEventListener('click', async () => {
  try {
    const { visionEnabled } = await chrome.storage.local.get('visionEnabled')
    await chrome.storage.local.set({ visionEnabled: !visionEnabled })
    await update()
  } catch {
    status.textContent = '无法更新视觉操作设置'
  }
})
void update()
