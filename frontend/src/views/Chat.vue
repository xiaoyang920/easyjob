<template>
  <div class="chat-page">
    <!-- 主容器 -->
    <div class="chat-container">
      <!-- 左侧：会话列表 -->
      <div :class="['conversation-list', { hidden: !showConversationList && currentConversation }]">
        <div class="conversation-header">
          <h3>消息列表</h3>
          <span class="unread-total" v-if="totalUnread > 0">{{ totalUnread }}</span>
        </div>
        
        <div class="conversation-search">
          <input 
            v-model="searchKeyword" 
            type="text" 
            placeholder="搜索用户..."
            @input="filterConversations"
          >
        </div>
        
        <div v-if="loadingConversations" class="loading-state">加载中...</div>
        <div v-else-if="filteredConversations.length === 0" class="empty-state">
          <p>暂无消息</p>
          <p class="tip">去关注一些用户，开始聊天吧</p>
        </div>
        <div v-else class="conversation-items">
          <div 
            v-for="conv in filteredConversations" 
            :key="conv.conversationId"
            :class="['conversation-item', { active: currentConversation?.conversationId === conv.conversationId }]"
            @click="selectConversation(conv)"
          >
            <img 
              :src="avatarUrl(conv.otherUserAvatar, conv.otherUserName)"
              :alt="conv.otherUserName"
              class="conversation-avatar"
              @error="onAvatarError($event, conv.otherUserName)"
            >
            <div class="conversation-info">
              <div class="conversation-name">{{ conv.otherUserName }}</div>
              <div class="conversation-last-msg">{{ conv.lastMessage || '暂无消息' }}</div>
            </div>
            <div class="conversation-meta">
              <div class="conversation-time">{{ formatTime(conv.lastMessageTime) }}</div>
              <span v-if="conv.unreadCount > 0" class="unread-badge">
                {{ conv.unreadCount > 99 ? '99+' : conv.unreadCount }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：聊天区域 -->
      <div class="chat-area">
        <!-- 未选择会话 -->
        <div v-if="!currentConversation" class="chat-placeholder">
          <div class="placeholder-icon">
            <svg viewBox="0 0 1024 1024" fill="currentColor">
              <path d="M535.552 796.444444H739.555556q70.712889 0 120.661333-50.005333Q910.222222 696.490667 910.222222 625.777778V341.333333q0-70.712889-50.005333-120.661333Q810.268444 170.666667 739.555556 170.666667H284.444444q-70.712889 0-120.661333 50.005333Q113.777778 270.620444 113.777778 341.333333v284.444445q0 70.712889 50.005333 120.661333Q213.731556 796.444444 284.444444 796.444444h13.084445q4.266667 8.533333 9.898667 16.497778 21.219556 30.151111 55.751111 44.487111 34.531556 14.279111 70.883555 7.964445 39.310222-6.826667 68.152889-35.612445L535.552 796.444444zM739.555556 682.666667H512a56.888889 56.888889 0 0 0-40.220444 16.668444l-50.005334 50.005333q-6.485333 6.485333-15.018666 2.958223Q398.222222 748.771556 398.222222 739.555556a56.888889 56.888889 0 0 0-56.888889-56.888889H284.444444q-23.552 0-40.220444-16.668445T227.555556 625.777778V341.333333q0-23.552 16.668444-40.220444T284.444444 284.444444h455.111112q23.552 0 40.220444 16.668445T796.444444 341.333333v284.444445q0 23.552-16.668444 40.220444T739.555556 682.666667zM341.333333 540.444444a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z"/>
            </svg>
          </div>
          <p>选择一个会话开始聊天</p>
        </div>

        <!-- 聊天内容 -->
        <template v-else>
          <!-- 聊天头部 -->
          <div class="chat-header">
            <button class="mobile-back-btn" @click="backToList">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
              </svg>
            </button>
            <img 
              :src="avatarUrl(currentConversation.otherUserAvatar, currentConversation.otherUserName)"
              :alt="currentConversation.otherUserName"
              class="chat-avatar"
              @click="goToUserSpace(currentConversation.otherUserId)"
              @error="onAvatarError($event, currentConversation.otherUserName)"
            >
            <div class="chat-user-info">
              <div class="chat-user-name" @click="goToUserSpace(currentConversation.otherUserId)">
                {{ currentConversation.otherUserName }}
              </div>
              <div :class="['chat-user-status', onlineStatus === '在线' ? 'online' : 'offline']">{{ onlineStatus }}</div>
            </div>
          </div>

          <!-- 消息列表 -->
          <div class="message-list" ref="messageListRef" :data-message-count="messages.length" :data-virtualized="messages.length > 60">
            <div v-if="loadingMessages" class="loading-messages">加载中...</div>
            <div v-if="hasMoreMessages && !loadingMessages" class="load-more" @click="loadMoreMessages">
              加载更多消息
            </div>
            
            <div ref="virtualSpacer" class="virtual-spacer" :style="{height:`${virtual.before.value}px`}" aria-hidden="true"></div>
            <div v-for="{item:msg,index} in virtual.items.value" :key="msg.messageId" :ref="virtual.measure" :data-virtual-key="String(msg.messageId)">
              <!-- 时间分隔线 -->
              <div v-if="showTimeDivider(index)" class="time-divider">
                {{ formatFullTime(msg.createTime) }}
              </div>
              
              <!-- 撤回消息 -->
              <div v-if="msg.status === 1" class="message-recalled">
                {{ msg.senderId === myUserId ? '你撤回了一条消息' : `${msg.senderName}撤回了一条消息` }}
              </div>
              
              <!-- 正常消息 -->
              <div v-else :class="['message-item', msg.senderId === myUserId ? 'self' : 'other']">
                <img 
                  v-if="msg.senderId !== myUserId"
                  :src="avatarUrl(msg.senderAvatar, msg.senderName)"
                  alt=""
                  class="msg-avatar"
                  @error="onAvatarError($event, msg.senderName)"
                >
                <div class="msg-content" :class="{ 'image-content': msg.messageType === 2 }">
                  <div class="msg-bubble" :class="{ 'image-bubble': msg.messageType === 2 }" @contextmenu.prevent="showMessageMenu($event, msg)">
                    <!-- 文本消息 -->
                    <template v-if="msg.messageType === 1">
                      {{ msg.content }}
                    </template>
                    <!-- 图片消息 -->
                    <template v-else-if="msg.messageType === 2">
                      <button class="image-message-button" aria-label="查看完整图片" @click="previewImage(msg.content, $event)">
                        <img :src="msg.content" alt="聊天图片" class="msg-image" loading="lazy">
                      </button>
                    </template>
                  </div>
                  <div class="msg-time">{{ formatMsgTime(msg.createTime) }}</div>
                </div>
                <img 
                  v-if="msg.senderId === myUserId"
                  :src="avatarUrl(myAvatar, myNickName)"
                  alt=""
                  class="msg-avatar"
                  @error="onAvatarError($event, myNickName)"
                >
              </div>
            </div>
            <div class="virtual-spacer" :style="{height:`${virtual.after.value}px`}" aria-hidden="true"></div>
          </div>

          <!-- 输入区域 -->
          <div class="input-area">
            <div class="input-tools">
              <!-- 表情按钮 -->
              <div class="tool-btn emoji-trigger" title="表情" @click.stop="toggleEmojiPicker">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/>
                </svg>
                <!-- 表情选择面板 -->
                <div v-if="showEmojiPicker" class="emoji-picker" @click.stop>
                  <div class="emoji-tabs">
                    <span 
                      v-for="(tab, index) in emojiTabs" 
                      :key="index"
                      :class="['emoji-tab', { active: currentEmojiTab === index }]"
                      @click="currentEmojiTab = index"
                    >{{ tab.name }}</span>
                  </div>
                  <div class="emoji-list">
                    <span 
                      v-for="emoji in emojiTabs[currentEmojiTab].emojis" 
                      :key="emoji"
                      class="emoji-item"
                      @click="insertEmoji(emoji)"
                    >{{ emoji }}</span>
                  </div>
                </div>
              </div>
              <!-- 图片按钮 -->
              <label class="tool-btn" title="发送图片">
                <svg viewBox="0 0 1024 1024" fill="currentColor">
                  <path d="M853.161077 892.549156 362.595248 892.549156l-209.432916-0.413416c-0.605797-0.001023-1.210571-0.031722-1.813299-0.092098-24.848944-2.484587-47.825238-14.060227-64.696488-32.594349-16.990976-18.665105-26.349111-42.85504-26.349111-68.112284L60.303434 264.62596c0-55.80805 45.403073-101.211123 101.211123-101.211123l691.645496 0c55.80805 0 101.2101 45.403073 101.2101 101.211123l0 225.51315c0 0.275269-0.00614 0.551562-0.01842 0.825808-0.021489 0.494257-1.971911 51.723012 15.481599 85.46244 4.716418 9.118682 1.14815 20.335141-7.970532 25.052582-9.116635 4.714372-20.335141 1.149173-25.052582-7.970532-21.300119-41.176818-19.844977-97.642854-19.618826-103.738689L917.191392 264.62596c0-35.307134-28.724205-64.031339-64.031339-64.031339L161.51558 200.594621c-35.307134 0-64.031339 28.724205-64.031339 64.031339l0 526.71105c0 32.755008 24.320918 59.957557 56.717769 63.61997l208.4311 0.412392 490.528989 0c35.307134 0 64.031339-28.725228 64.031339-64.032362l-0.382717-93.676519c-0.104377-1.749854-1.587148-19.548218-19.549242-42.499953-0.050142-0.063445-0.098237-0.125867-0.147356-0.190335L875.401614 626.481358 758.174726 471.362464c-0.415462-0.550539-38.995129-50.852178-86.271876-45.534056-38.335097 4.314259-75.954903 45.163619-108.789729 118.131491-17.615193 39.141462-34.650171 68.26885-52.082192 89.046059-17.607006 20.985964-35.679617 33.519418-55.251372 38.316677-43.422975 10.638291-81.049944-18.99461-120.886231-50.372248l-5.057179-3.980661c-46.555315-36.57808-68.750827-28.223808-158.330028 59.60247-7.330966 7.187703-19.101033 7.071046-26.288736-0.25992-7.187703-7.330966-7.071046-19.101033 0.25992-26.287713 46.658669-45.74588 77.544097-72.726372 107.085924-84.282568 33.357735-13.048177 64.274886-6.266727 100.242052 21.99392l5.092995 4.00829c33.9226 26.719548 63.219857 49.795103 89.028663 43.466977 25.618471-6.279007 53.30095-42.114167 82.279958-106.508779 39.139415-86.97591 85.837994-134.027529 138.79716-139.849118 68.454068-7.515161 117.823476 57.404408 119.891578 60.171428l117.122511 154.980747 21.599947 28.343535c26.276457 33.630958 27.333532 61.638849 27.367301 64.72514 0.001023 0.042979 0.001023 0.084934 0.001023 0.127913l0.38374 94.059236C954.371176 847.146083 908.969127 892.549156 853.161077 892.549156z"/>
                  <path d="M312.328401 446.967868c-42.324968 0-76.759221-34.434254-76.759221-76.759221s34.434254-76.759221 76.759221-76.759221 76.759221 34.434254 76.759221 76.759221S354.654392 446.967868 312.328401 446.967868zM312.328401 330.628186c-21.824051 0-39.579437 17.755386-39.579437 39.579437s17.755386 39.579437 39.579437 39.579437 39.579437-17.755386 39.579437-39.579437S334.153476 330.628186 312.328401 330.628186z"/>
                </svg>
                <input type="file" accept="image/*" @change="handleImageUpload" hidden>
              </label>
            </div>
            <div class="input-wrapper">
              <textarea 
                v-model="messageInput"
                placeholder="输入消息..."
                @keydown.enter.exact.prevent="sendMessage"
                @keydown.enter.shift.exact="newLine"
                rows="1"
                ref="inputRef"
              ></textarea>
            </div>
            <!-- 上传进度 -->
            <div v-if="imageUploading" class="chat-upload-progress">
              <div class="progress-bar" :style="{ width: imageUploadProgress + '%' }"></div>
              <span class="progress-text">{{ imageUploadProgress }}%</span>
            </div>
            <button class="send-btn" @click="sendMessage" :disabled="!messageInput.trim()">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
        </template>
      </div>
    </div>

    <Teleport to="body">
    <!-- 图片预览 -->
    <div v-if="previewImageUrl" class="image-preview-overlay" role="dialog" aria-modal="true" aria-label="图片预览" @click="closeImagePreview" @keydown.esc="closeImagePreview" @keydown.tab.prevent="previewCloseRef?.focus()">
      <button ref="previewCloseRef" class="preview-close" aria-label="关闭图片预览" @click.stop="closeImagePreview">×</button>
      <img :src="previewImageUrl" alt="完整聊天图片" class="preview-image" @click.stop>
    </div>

    </Teleport>

    <!-- 消息右键菜单 -->
    <div 
      v-if="contextMenu.visible" 
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <div 
        v-if="contextMenu.message?.senderId === myUserId && canRecall(contextMenu.message)" 
        class="menu-item" 
        @click="recallMessage"
      >
        撤回
      </div>
      <div class="menu-item" @click="copyMessage">复制</div>
    </div>

    <!-- 登录弹窗 -->
    <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>
    <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
      <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { useVirtualMessages } from '@/composables/useVirtualMessages'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { goBackOr } from '@/utils/navigation'
import { ElMessage } from 'element-plus'
import LoginForm from '@/components/LoginForm.vue'
import RegisterForm from '@/components/RegisterForm.vue'
import request from '@/utils/request'
import { uploadFile } from '@/utils/upload'
import { ensureAccessToken } from '@/utils/authSession'
import { eventBus, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'
import { avatarUrl, onAvatarError } from '@/utils/avatar'

const router = useRouter()
const route = useRoute()

// 当前用户信息（从本地缓存读取）
const myUserId = ref(localStorage.getItem('userId') || '')
const myAvatar = ref(localStorage.getItem('avatar') || '')
const myNickName = ref(localStorage.getItem('nickName') || '')

// 会话列表
const conversations = ref<any[]>([])
const filteredConversations = ref<any[]>([])
const currentConversation = ref<any>(null)
const loadingConversations = ref(false)
const searchKeyword = ref('')
const showConversationList = ref(true)  // 移动端控制会话列表显示

// 消息列表
const messages = ref<any[]>([])
const loadingMessages = ref(false)
const hasMoreMessages = ref(false)
const lastMessageId = ref<string | null>(null)

// 输入
const messageInput = ref('')
const messageListRef = ref<HTMLElement>()
const virtual = useVirtualMessages(() => messages.value, messageListRef, m => String(m.messageId), m => m.messageType === 1 ? 300 : 100 + Math.min(300,String(m.content || '').length / 40 * 22))
const virtualSpacer = virtual.spacer
const inputRef = ref<HTMLTextAreaElement>()
const imageUploading = ref(false)
const imageUploadProgress = ref(0)

// 图片预览
const previewImageUrl = ref('')
const previewCloseRef = ref<HTMLButtonElement>()
let previewTrigger: HTMLElement | null = null

// 表情选择
const showEmojiPicker = ref(false)
const currentEmojiTab = ref(0)
const emojiTabs = [
  {
    name: '常用',
    emojis: ['😀', '😁', '😂', '🤣', '😃', '😄', '😅', '😆', '😉', '😊', '😋', '😎', '😍', '🥰', '😘', '😗', '😙', '😚', '🙂', '🤗', '🤩', '🤔', '🤨', '😐', '😑', '😶', '🙄', '😏', '😣', '😥', '😮', '🤐', '😯', '😪', '😫', '🥱', '😴', '😌', '😛', '😜', '😝', '🤤', '😒', '😓', '😔', '😕', '🙃', '🤑', '😲', '🙁', '😖', '😞', '😟', '😤', '😢', '😭', '😦', '😧', '😨', '😩', '🤯', '😬', '😰', '😱']
  },
  {
    name: '手势',
    emojis: ['👍', '👎', '👌', '🤌', '🤏', '✌️', '🤞', '🤟', '🤘', '🤙', '👈', '👉', '👆', '👇', '☝️', '👋', '🤚', '🖐️', '✋', '🖖', '👏', '🙌', '🤲', '🤝', '🙏', '✍️', '💪', '🦵', '🦶', '👂', '🦻', '👃', '👀', '👁️', '👅', '👄', '💋', '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💔', '❤️‍🔥', '💕', '💞', '💓', '💗', '💖', '💘', '💝']
  },
  {
    name: '动物',
    emojis: ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷', '🐸', '🐵', '🐔', '🐧', '🐦', '🐤', '🦆', '🦅', '🦉', '🦇', '🐺', '🐗', '🐴', '🦄', '🐝', '🐛', '🦋', '🐌', '🐞', '🐜', '🦟', '🦗', '🕷️', '🦂', '🐢', '🐍', '🦎', '🦖', '🦕', '🐙', '🦑', '🦐', '🦞', '🦀', '🐡', '🐠', '🐟', '🐬', '🐳', '🐋', '🦈', '🐊']
  },
  {
    name: '食物',
    emojis: ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🫐', '🍈', '🍒', '🍑', '🥭', '🍍', '🥥', '🥝', '🍅', '🍆', '🥑', '🥦', '🥬', '🥒', '🌶️', '🫑', '🌽', '🥕', '🫒', '🧄', '🧅', '🥔', '🍠', '🥐', '🥯', '🍞', '🥖', '🥨', '🧀', '🥚', '🍳', '🧈', '🥞', '🧇', '🥓', '🥩', '🍗', '🍖', '🦴', '🌭', '🍔', '🍟', '🍕', '🫓', '🥪', '🥙', '🧆', '🌮']
  }
]

// 右键菜单
const contextMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  message: null as any
})

// WebSocket
let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let heartbeatTimer: number | null = null
let shouldReconnect = true  // 控制是否应该重连

// 用户在线状态缓存
const onlineUsers = ref<Set<string>>(new Set())

// 计算总未读数
const totalUnread = computed(() => {
  return conversations.value.reduce((sum, c) => sum + (c.unreadCount || 0), 0)
})

// 在线状态
const onlineStatus = computed(() => {
  if (!currentConversation.value) return ''
  return onlineUsers.value.has(currentConversation.value.otherUserId) ? '在线' : '离线'
})

// 检查并加载用户信息（兆底逻辑，确保头像和昵称已缓存）
async function ensureUserInfo() {
  // 如果本地缓存没有头像或昵称，调用接口获取
  if (!myAvatar.value || !myNickName.value) {
    try {
      const userId = localStorage.getItem('userId')
      if (!userId) return
      
      const res = await request.get(`/user/space/${userId}`)
      if (res.code === 200 && res.data) {
        if (res.data.nickName) {
          myNickName.value = res.data.nickName
          localStorage.setItem('nickName', res.data.nickName)
        }
        if (res.data.avatar) {
          myAvatar.value = res.data.avatar
          localStorage.setItem('avatar', res.data.avatar)
        }
      }
    } catch (error) {
      console.error('获取用户信息失败:', error)
    }
  }
}

// 获取会话列表
async function fetchConversations() {
  loadingConversations.value = true
  try {
    const res = await request.get('/chat/conversations')
    if (res.code === 200 && res.data) {
      conversations.value = res.data
      filteredConversations.value = res.data
      
      // 如果URL有指定用户，自动选中或创建会话
      const targetUserId = route.query.userId
      if (targetUserId) {
        const existConv = conversations.value.find(c => c.otherUserId == targetUserId)
        if (existConv) {
          selectConversation(existConv)
        } else {
          await createConversation(targetUserId as string)
        }
      }
    }
  } catch (error) {
    console.error('获取会话列表失败:', error)
  } finally {
    loadingConversations.value = false
  }
}

// 创建新会话
async function createConversation(targetUserId: string) {
  try {
    const res = await request.post('/chat/conversation/create', { targetUserId: String(targetUserId) })
    if (res.code === 200 && res.data) {
      // 检查是否已存在（可能是返回的已有会话）
      const existIndex = conversations.value.findIndex(c => c.conversationId === res.data.conversationId)
      if (existIndex === -1) {
        conversations.value.unshift(res.data)
      }
      filteredConversations.value = conversations.value
      selectConversation(res.data)
    }
  } catch (error) {
    console.error('创建会话失败:', error)
  }
}

// 选择会话
async function selectConversation(conv: any) {
  currentConversation.value = conv
  lastMessageId.value = null
  messages.value = []
  
  // 移动端隐藏会话列表
  if (window.innerWidth <= 768) {
    showConversationList.value = false
  }
  
  // 获取消息历史
  await fetchMessages()
  
  // 标记已读
  if (conv.unreadCount > 0) {
    markAsRead(conv.conversationId)
  }
  
  // 滚动到底部
  scrollToBottom()
}

// 移动端返回会话列表
function backToList() {
  showConversationList.value = true
}

// 获取消息历史
async function fetchMessages(loadMore = false) {
  if (!currentConversation.value) return
  
  const cid = currentConversation.value.conversationId
  loadingMessages.value = true
  try {
    const params: any = {
      conversationId: currentConversation.value.conversationId,
      size: 20
    }
    if (loadMore && lastMessageId.value) {
      params.lastMessageId = lastMessageId.value
    }
    
    const res = await request.get('/chat/messages', { params })
    if (currentConversation.value?.conversationId !== cid) return
    
    if (res.code === 200 && res.data) {
      const newMessages = res.data.records || []
      hasMoreMessages.value = res.data.hasMore
      
      if (newMessages.length > 0) {
        // 记录最早的消息ID，用于下次分页
        lastMessageId.value = newMessages.at(-1).messageId
      }
      
      if (loadMore) {
        // 加载更多：插入到前面
        mergeMessages(newMessages)
      } else {
        // 首次加载：反转顺序（接口返回倒序，显示要正序）
        mergeMessages(newMessages)
      }
    }
  } catch (error) {
    console.error('获取消息失败:', error)
  } finally {
    loadingMessages.value = false
  }
}

// 加载更多消息
async function loadMoreMessages() {
  const anchor = virtual.captureAnchor()
  await fetchMessages(true)
  await nextTick()
  await virtual.restoreAnchor(anchor)
}

// 发送消息
const sending = ref(false)
let pendingSend: { cid: string, content: string, id: string } | null = null

function mergeMessages(incoming: any[]) {
  const byId = new Map(messages.value.map(m => [m.messageId, m]))
  for (const message of incoming) byId.set(message.messageId, { ...byId.get(message.messageId), ...message })
  messages.value = [...byId.values()].sort((a, b) => BigInt(a.messageId) < BigInt(b.messageId) ? -1 : BigInt(a.messageId) > BigInt(b.messageId) ? 1 : 0)
}

async function catchUpMessages() {
  const cid = currentConversation.value?.conversationId
  if (!cid) return
  // Refresh the visible page as well to catch recalls during disconnection.
  const latest = await request.get('/chat/messages', { params: { conversationId: cid, size: 100 } })
  if (currentConversation.value?.conversationId !== cid) return
  let after = messages.value.at(-1)?.messageId || '0'
  mergeMessages(latest.data?.records || [])
  for (let page = 0; page < 20; page++) {
    const res = await request.get('/chat/messages/after', { params: { conversationId: cid, afterMessageId: after, size: 100 } })
    if (currentConversation.value?.conversationId !== cid) return
    const rows = res.data?.records || []
    mergeMessages(rows)
    if (!res.data?.hasMore || !rows.length) break
    after = rows.at(-1).messageId
  }
  await markAsRead(cid)
}

async function sendMessage() {
  const content = messageInput.value.trim()
  if (!content || !currentConversation.value || sending.value) return
  const cid = currentConversation.value.conversationId
  if (!pendingSend || pendingSend.cid !== cid || pendingSend.content !== content) pendingSend = { cid, content, id: crypto.randomUUID() }
  sending.value = true
  try {
    const res = await request.post('/chat/message/send', {
      conversationId: currentConversation.value.conversationId,
      messageType: 1,
      content: content,
      clientMessageId: pendingSend.id
    })
    
    if (res.code === 200 && res.data) {
      // 使用本地缓存的用户信息，避免后端重复查询
      // 添加到消息列表
      if (currentConversation.value?.conversationId === cid) mergeMessages([res.data])
      pendingSend = null
      messageInput.value = ''
      
      // 更新会话列表的最后消息
      updateConversationLastMessage(content)
      
      // 滚动到底部
      scrollToBottom()
    } else {
      ElMessage.error(res.message || '发送失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '发送失败，可再次发送重试')
  } finally { sending.value = false }
}

// 处理图片上传
async function handleImageUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file || !currentConversation.value) return
  
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('图片大小不能超过5MB')
    return
  }
  
  imageUploading.value = true
  imageUploadProgress.value = 0
  
  try {
    // 上传图片
    const uploadRes = await uploadFile({
      url: '/file/upload-message',
      file,
      onProgress: (percent) => {
        imageUploadProgress.value = percent
      }
    })
    
    if (uploadRes.code === 200 && uploadRes.data?.url) {
      // 发送图片消息
      const res = await request.post('/chat/message/send', {
        conversationId: currentConversation.value.conversationId,
        messageType: 2,
        content: uploadRes.data.url,
        clientMessageId: crypto.randomUUID()
      })
      
      if (res.code === 200 && res.data) {
        // 使用本地缓存的用户信息
        mergeMessages([res.data])
        updateConversationLastMessage('[图片]', 2)
        scrollToBottom()
      }
    }
  } catch (error: any) {
    ElMessage.error(error.message || '发送图片失败')
  } finally {
    imageUploading.value = false
    imageUploadProgress.value = 0
  }
  
  target.value = ''
}

// 标记已读
async function markAsRead(conversationId: string) {
  try {
    await request.post(`/chat/conversation/${conversationId}/read`)
    // 更新本地未读数
    const conv = conversations.value.find(c => c.conversationId === conversationId)
    if (conv) {
      conv.unreadCount = 0
    }
  } catch (error) {
    console.error('标记已读失败:', error)
  }
}

// 更新会话最后消息
function updateConversationLastMessage(content: string, messageType: number = 1) {
  if (!currentConversation.value) return
  
  const conv = conversations.value.find(c => c.conversationId === currentConversation.value.conversationId)
  if (conv) {
    // 如果是图片消息，显示[图片]而不是路径
    conv.lastMessage = messageType === 2 ? '[图片]' : content
    conv.lastMessageTime = new Date().toISOString()
    
    // 移动到顶部
    const index = conversations.value.indexOf(conv)
    if (index > 0) {
      conversations.value.splice(index, 1)
      conversations.value.unshift(conv)
      filteredConversations.value = conversations.value
    }
  }
}

// 撤回消息
async function recallMessage() {
  if (!contextMenu.value.message) return
  
  try {
    const res = await request.post(`/chat/message/${contextMenu.value.message.messageId}/recall`)
    if (res.code === 200) {
      // 更新本地消息状态
      const msg = messages.value.find(m => m.messageId === contextMenu.value.message.messageId)
      if (msg) {
        msg.status = 1
      }
      // 同步更新左侧会话列表的 lastMessage
      refreshLastMessageAfterRecall()
      ElMessage.success('消息已撤回')
    } else {
      ElMessage.error(res.message || '撤回失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '撤回失败')
  }
  
  contextMenu.value.visible = false
}

// 撤回后刷新会话列表的最后一条消息
function refreshLastMessageAfterRecall() {
  if (!currentConversation.value) return
  
  const conv = conversations.value.find(c => c.conversationId === currentConversation.value.conversationId)
  if (conv) {
    conv.lastMessage = '你撤回了一条消息'
  }
}

// 复制消息
function copyMessage() {
  if (!contextMenu.value.message) return
  
  navigator.clipboard.writeText(contextMenu.value.message.content)
  ElMessage.success('已复制到剪贴板')
  contextMenu.value.visible = false
}

// 判断是否可以撤回（2分钟内）
function canRecall(msg: any): boolean {
  if (!msg) return false
  const createTime = new Date(msg.createTime).getTime()
  const now = Date.now()
  return now - createTime < 2 * 60 * 1000
}

// 显示消息右键菜单
function showMessageMenu(e: MouseEvent, msg: any) {
  contextMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    message: msg
  }
}

// 初始化WebSocket
async function initWebSocket() {
  let token: string | null
  try { token = await ensureAccessToken() } catch { return }
  if (!token) return
  
  // 如果已经有连接，先关闭
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return
  }
  
  shouldReconnect = true
  
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsHost = window.location.host
  ws = new WebSocket(`${wsProtocol}//${wsHost}/ws/chat?token=${token}`)
  
  ws.onopen = () => {
    console.log('WebSocket连接成功')
    startHeartbeat()
    fetchConversations()
    catchUpMessages().catch(() => ElMessage.warning('网络已连接，消息同步失败，可重新打开会话'))
  }
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    handleWsMessage(data)
  }
  
  ws.onclose = () => {
    console.log('WebSocket连接关闭')
    stopHeartbeat()
    // 只有应该重连时才重连
    if (shouldReconnect) {
      reconnectTimer = window.setTimeout(() => {
        initWebSocket()
      }, 3000)
    }
  }
  
  ws.onerror = (error) => {
    console.error('WebSocket错误:', error)
  }
}

// 处理WebSocket消息
function handleWsMessage(data: any) {
  if (data.type === 'message') {
    // 收到新消息
    if (currentConversation.value && data.conversationId === currentConversation.value.conversationId) {
      // 当前会话的消息
      mergeMessages([data])
      markAsRead(currentConversation.value.conversationId)
      scrollToBottom()
    } else {
      // 其他会话的消息，更新未读数
      const conv = conversations.value.find(c => c.conversationId === data.conversationId)
      if (conv) {
        conv.unreadCount = data.senderId === myUserId.value ? 0 : (conv.unreadCount || 0) + 1
        conv.lastMessage = data.messageType === 2 ? '[图片]' : data.content
        conv.lastMessageTime = data.createTime
        // 将会话移动到顶部
        moveConversationToTop(conv)
      } else {
        // 新会话，重新获取会话列表
        fetchConversations()
      }
    }
  } else if (data.type === 'recall') {
    // 消息撤回
    const msg = messages.value.find(m => m.messageId === data.messageId)
    if (msg) {
      msg.status = 1
    }
    // 同步更新会话列表的 lastMessage
    const conv = conversations.value.find(c => c.conversationId === data.conversationId)
    if (conv) {
      conv.lastMessage = data.senderId === myUserId.value ? '你撤回了一条消息' : '[消息已撤回]'
    }
  } else if (data.type === 'online') {
    // 用户上线
    onlineUsers.value.add(data.userId)
  } else if (data.type === 'offline') {
    // 用户下线
    onlineUsers.value.delete(data.userId)
  } else if (data.type === 'online_users') {
    // 初始化在线用户列表
    onlineUsers.value = new Set(data.userIds || [])
  } else if (data.type === 'unread_update') {
    // 未读数更新
    const conv = conversations.value.find(c => c.conversationId === data.conversationId)
    if (conv) {
      conv.unreadCount = data.unreadCount
    }
  }
}

// 将会话移动到列表顶部
function moveConversationToTop(conv: any) {
  const index = conversations.value.indexOf(conv)
  if (index > 0) {
    conversations.value.splice(index, 1)
    conversations.value.unshift(conv)
    filteredConversations.value = [...conversations.value]
  }
}

// 心跳
function startHeartbeat() {
  heartbeatTimer = window.setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

// 搜索过滤
function filterConversations() {
  if (!searchKeyword.value.trim()) {
    filteredConversations.value = conversations.value
  } else {
    filteredConversations.value = conversations.value.filter(c => 
      c.otherUserName?.includes(searchKeyword.value)
    )
  }
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

// 跳转到用户空间
function goToUserSpace(userId: string) {
  router.push(`/user-space/${userId}`)
}

// 预览图片
function previewImage(url: string, event: MouseEvent) {
  previewTrigger = event.currentTarget as HTMLElement
  previewImageUrl.value = url
  nextTick(() => previewCloseRef.value?.focus())
}

function closeImagePreview() {
  previewImageUrl.value = ''
  nextTick(() => previewTrigger?.focus())
}

// 是否显示时间分隔线
function showTimeDivider(index: number): boolean {
  if (index === 0) return true
  const curr = new Date(messages.value[index].createTime)
  const prev = new Date(messages.value[index - 1].createTime)
  // 超过5分钟显示时间
  return curr.getTime() - prev.getTime() > 5 * 60 * 1000
}

// 格式化时间
function formatTime(timeStr: string): string {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
  }
  
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) {
    return '昨天'
  }
  
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function formatMsgTime(timeStr: string): string {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

function formatFullTime(timeStr: string): string {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return `今天 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
  }
  
  return `${date.getMonth() + 1}月${date.getDate()}日 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

// 换行
function newLine() {
  messageInput.value += '\n'
}

// 切换表情选择器
function toggleEmojiPicker() {
  showEmojiPicker.value = !showEmojiPicker.value
}

// 插入表情
function insertEmoji(emoji: string) {
  messageInput.value += emoji
  // 聚焦输入框
  inputRef.value?.focus()
}

// 关闭表情选择器
function closeEmojiPicker() {
  showEmojiPicker.value = false
}

// 点击其他区域关闭右键菜单和表情选择器
function closeContextMenu() {
  contextMenu.value.visible = false
  showEmojiPicker.value = false
}

// 监听路由变化
watch(() => route.query.userId, (newUserId) => {
  if (newUserId && conversations.value.length > 0) {
    const existConv = conversations.value.find(c => c.otherUserId == newUserId)
    if (existConv) {
      selectConversation(existConv)
    } else {
      createConversation(newUserId as string)
    }
  }
})

// 登录弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const dialogWidth = ref(window.innerWidth <= 480 ? '92%' : '420px')

// 登录过期处理：跳转首页并弹出登录弹窗
function handleAuthExpired() {
  // 关闭WebSocket连接
  shouldReconnect = false
  if (ws) {
    ws.close()
    ws = null
  }
  stopHeartbeat()
  showLoginDialog.value = true
}

function handleLoginSuccess() {
  showLoginDialog.value = false
  location.reload()
}

function handleRegisterSuccess() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

function switchToRegister() {
  showLoginDialog.value = false
  showRegisterDialog.value = true
}

function switchToLogin() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

onMounted(async () => {
  if (!localStorage.getItem('token')) {
    showLoginDialog.value = true
    return
  }
  
  // 监听登录过期事件
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  
  // 确保用户信息已缓存（兆底逻辑）
  await ensureUserInfo()
  
  fetchConversations()
  initWebSocket()
  
  // 监听点击事件关闭右键菜单
  document.addEventListener('click', closeContextMenu)
})

onUnmounted(() => {
  // 移除登录过期事件监听
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  // 停止重连
  shouldReconnect = false
  
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.close()
    ws = null
  }
  stopHeartbeat()
  document.removeEventListener('click', closeContextMenu)
})
</script>

<style scoped>
.chat-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
  overflow: hidden;
}

.chat-page::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--ej-canvas);
  z-index: -2;
}

/* 导航栏 */
.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 70px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 28px;
  font-weight: bold;
  color: var(--ej-accent);
  cursor: pointer;
}

.logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  fill: var(--ej-accent);
}

.logo-text {
  display: inline;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.nav-right {
  display: flex;
  gap: 15px;
}

.nav-btn {
  background: transparent;
  color: #666;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
}

/* 主容器 */
.chat-container {
  margin-top: 70px;
  height: calc(100vh - 70px);
  display: flex;
  max-width: 1400px;
  margin-left: auto;
  margin-right: auto;
  padding: 20px;
  gap: 20px;
}

/* 会话列表：纸面、墨线边框与偏移阴影见 styles/theme.css，左右两栏使用同一套外框 */
.conversation-list {
  width: 320px;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.conversation-header {
  padding: 20px;
  border-bottom: 1px solid var(--ej-hairline);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.conversation-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--ej-ink);
}

.unread-total {
  padding: 2px 8px;
  border: 1px solid var(--ej-ink);
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
}

.conversation-search {
  padding: 14px 20px;
  border-bottom: 1px solid var(--ej-hairline);
}

.conversation-search input {
  width: 100%;
  padding: 10px 15px;
  border: 1px solid var(--ej-line);
  border-radius: 999px;
  outline: none;
  font-size: 13px;
  color: var(--ej-ink);
  background: var(--ej-canvas);
  transition: border-color 0.2s, background 0.2s, box-shadow 0.25s;
}

.conversation-search input::placeholder {
  color: var(--ej-muted);
}

.conversation-search input:focus {
  border-color: var(--ej-ink);
  background: var(--ej-surface);
  box-shadow: 3px 3px 0 #11110f14;
}

.conversation-items {
  flex: 1;
  overflow-y: auto;
}

.conversation-item {
  display: flex;
  align-items: center;
  padding: 15px 20px;
  cursor: pointer;
  transition: background 0.2s;
  border-bottom: 1px solid var(--ej-hairline);
}

.conversation-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  object-fit: cover;
  margin-right: 12px;
  border: 1px solid var(--ej-ink);
}

.conversation-info {
  flex: 1;
  min-width: 0;
}

.conversation-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--ej-ink);
  margin-bottom: 4px;
}

.conversation-last-msg {
  font-size: 13px;
  color: var(--ej-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conversation-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
}

.conversation-time {
  font-size: 12px;
  color: var(--ej-muted);
}

.unread-badge {
  padding: 1px 6px;
  border: 1px solid var(--ej-ink);
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  min-width: 18px;
  text-align: center;
}

/* 聊天区域 */
.chat-area {
  flex: 1;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ej-muted);
}

.placeholder-icon {
  width: 80px;
  height: 80px;
  margin-bottom: 20px;
  color: var(--ej-soft);
}

.placeholder-icon svg {
  width: 100%;
  height: 100%;
}

.chat-header {
  padding: 15px 20px;
  border-bottom: 1px solid var(--ej-hairline);
  display: flex;
  align-items: center;
  gap: 12px;
}

.mobile-back-btn {
  display: none;
  width: 36px;
  height: 36px;
  border: 1px solid var(--ej-line);
  background: var(--ej-canvas);
  border-radius: 50%;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  color: var(--ej-ink);
  transition: background 0.2s, border-color 0.2s;
  flex-shrink: 0;
}

.mobile-back-btn:hover {
  background: var(--studio-lime);
  border-color: var(--ej-ink);
}

.mobile-back-btn svg {
  width: 20px;
  height: 20px;
}

.chat-avatar {
  width: 45px;
  height: 45px;
  border-radius: 50%;
  object-fit: cover;
  cursor: pointer;
}

.chat-user-info {
  flex: 1;
}

.chat-user-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ej-ink);
  cursor: pointer;
}

.chat-user-name:hover {
  color: var(--ej-accent);
}

.chat-user-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ej-muted);
}

/* 在线状态用小圆点表达：在线为青柠色，离线为空心 */
.chat-user-status::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1px solid var(--ej-ink);
  background: transparent;
}

.chat-user-status.online {
  color: var(--ej-ink);
}

.chat-user-status.online::before {
  background: var(--studio-lime);
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.loading-messages,
.loading-state {
  text-align: center;
  padding: 20px;
  color: var(--ej-muted);
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--ej-muted);
}

.empty-state .tip {
  font-size: 12px;
  margin-top: 8px;
}

.load-more {
  text-align: center;
  padding: 10px;
  color: var(--ej-accent);
  cursor: pointer;
  font-size: 13px;
}

.load-more:hover {
  text-decoration: underline;
}

/* 时间分隔：两侧细线中间是日期 */
.time-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 15px 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ej-muted);
}

.time-divider::before,
.time-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--ej-hairline);
}

.message-recalled {
  text-align: center;
  padding: 10px 0;
  font-size: 12px;
  color: var(--ej-muted);
}

.message-item {
  display: flex;
  align-items: flex-start;
  margin-bottom: 15px;
  gap: 10px;
}

.message-item.self {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid var(--ej-ink);
}

.msg-content {
  max-width: 60%;
}

.msg-bubble {
  padding: 12px 16px;
  border-radius: 18px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

/* 对方的气泡用暖灰纸色，与聊天区的米白底区分开；自己的气泡见 styles/theme.css */
.message-item.other .msg-bubble {
  background: var(--ej-canvas);
  color: var(--ej-ink);
  border-top-left-radius: 4px;
}

.message-item.self .msg-bubble {
  background: var(--ej-accent);
  color: white;
  border-top-right-radius: 4px;
}

.msg-image {
  display: block;
  width: auto;
  height: auto;
  max-width: min(320px, 100%);
  max-height: 360px;
  object-fit: contain;
  border-radius: 10px;
  cursor: pointer;
}

.image-message-button {
  display: block;
  max-width: 100%;
  padding: 0;
  border: 0;
  border-radius: 10px;
  background: transparent;
  cursor: zoom-in;
}

.image-message-button:focus-visible { outline: 2px solid var(--ej-ink); outline-offset: 4px; }

.preview-close {
  position: absolute;
  top: max(20px, env(safe-area-inset-top));
  right: 20px;
  width: 40px;
  height: 40px;
  border: 1px solid #ffffff80;
  border-radius: 50%;
  background: #11110f;
  color: white;
  font-size: 26px;
  cursor: pointer;
}

.msg-time {
  font-size: 11px;
  color: var(--ej-muted);
  margin-top: 5px;
  padding: 0 5px;
}

.message-item.self .msg-time {
  text-align: right;
}

/* 输入区域 */
.input-area {
  padding: 14px 20px;
  border-top: 1px solid var(--ej-hairline);
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.input-tools {
  display: flex;
  gap: 4px;
}

.tool-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 50%;
  cursor: pointer;
  color: var(--ej-ink);
  transition: background 0.2s, border-color 0.2s;
}

.tool-btn:hover {
  background: var(--studio-lime);
  border-color: var(--ej-ink);
}

.tool-btn svg {
  width: 22px;
  height: 22px;
}

/* 输入框与 AI 助手的输入区同一种外观：暖灰底，聚焦时墨线描边加偏移阴影 */
.input-wrapper {
  flex: 1;
  background: var(--ej-canvas);
  border: 1px solid var(--ej-line);
  border-radius: 20px;
  padding: 10px 15px;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.25s;
}

.input-wrapper:focus-within {
  background: var(--ej-surface);
  border-color: var(--ej-ink);
  box-shadow: 3px 3px 0 #11110f14;
}

.input-wrapper textarea {
  width: 100%;
  border: none;
  background: transparent;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  color: var(--ej-ink);
  max-height: 100px;
}

.input-wrapper textarea::placeholder {
  color: var(--ej-muted);
}

/* 上传进度 */
.chat-upload-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--ej-canvas);
  border-radius: 8px;
  margin-right: 10px;
}
.chat-upload-progress .progress-bar {
  height: 4px;
  background: var(--ej-accent);
  border-radius: 2px;
  transition: width 0.2s ease;
  min-width: 4px;
  max-width: 60px;
}
.chat-upload-progress .progress-text {
  font-size: 12px;
  color: var(--ej-accent);
  font-weight: 500;
  min-width: 32px;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--ej-accent);
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.send-btn:hover:not(:disabled) {
  background: var(--ej-ink);
}

.send-btn:disabled {
  background: var(--ej-soft);
  color: var(--ej-muted);
  border-color: var(--ej-line);
  cursor: not-allowed;
}

.send-btn svg {
  width: 20px;
  height: 20px;
}

/* 图片预览 */
.image-preview-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #11110fe0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  cursor: pointer;
}

.preview-image {
  width: auto;
  height: auto;
  max-width: calc(100% - 32px);
  max-height: calc(100dvh - 100px);
  object-fit: contain;
}

/* 右键菜单：与全站下拉菜单一致的纸面 + 墨线 + 偏移阴影 */
.context-menu {
  position: fixed;
  padding: 6px;
  background: var(--ej-surface);
  border: 1px solid var(--ej-ink);
  border-radius: 14px;
  box-shadow: 4px 4px 0 #11110f26;
  z-index: 9999;
  min-width: 112px;
  overflow: hidden;
}

.menu-item {
  padding: 9px 14px;
  border-radius: 9px;
  cursor: pointer;
  font-size: 14px;
  color: var(--ej-ink);
  transition: background 0.2s;
}

.menu-item:hover {
  background: var(--studio-lime);
}

/* 表情选择器 */
.emoji-trigger {
  position: relative;
}

.emoji-picker {
  position: absolute;
  bottom: 45px;
  left: 0;
  width: 320px;
  max-width: calc(100vw - 40px);
  background: var(--ej-surface);
  border: 1px solid var(--ej-ink);
  border-radius: 16px;
  box-shadow: 4px 4px 0 #11110f26;
  z-index: 1000;
  overflow: hidden;
}

.emoji-tabs {
  display: flex;
  border-bottom: 1px solid var(--ej-hairline);
  padding: 8px 10px;
  gap: 5px;
}

.emoji-tab {
  padding: 5px 12px;
  font-size: 13px;
  color: var(--ej-muted);
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: 999px;
  transition: background 0.2s, border-color 0.2s;
}

.emoji-tab:hover {
  background: var(--ej-canvas);
  color: var(--ej-ink);
}

.emoji-tab.active {
  background: var(--studio-lime);
  border-color: var(--ej-ink);
  color: var(--ej-ink);
}

.emoji-list {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 5px;
  padding: 10px;
  max-height: 200px;
  overflow-y: auto;
}

.emoji-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 20px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.2s;
}

.emoji-item:hover {
  background: var(--studio-lime-soft);
}

/* 平板适配 */
@media (max-width: 900px) {
  .conversation-list {
    width: 280px;
  }
}

/* 手机适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 55px;
  }
  
  .logo {
    font-size: 20px;
  }
  
  .page-title {
    font-size: 16px;
  }
  
  .nav-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  .chat-container {
    margin-top: 55px;
    height: calc(100vh - 55px);
  }
  
  /* 移动端会话列表和聊天区域切换 */
  .conversation-list {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    z-index: 10;
    transition: transform 0.3s ease;
  }
  
  .conversation-list.hidden {
    transform: translateX(-100%);
  }
  
  .chat-area {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
  }
  
  .chat-header {
    padding: 12px 15px;
  }
  
  /* 移动端返回按钮 */
  .mobile-back-btn {
    display: flex;
  }
  
  .chat-user-name {
    font-size: 15px;
  }
  
  .chat-messages {
    padding: 15px;
  }
  
  .message-avatar {
    width: 32px;
    height: 32px;
  }
  
  .message-bubble {
    max-width: 75%;
    padding: 10px 12px;
    font-size: 14px;
  }
  
  .chat-input-area {
    padding: 10px 12px;
  }
  
  .chat-input-wrapper {
    gap: 8px;
  }
  
  .chat-input-wrapper input {
    padding: 10px 12px;
    font-size: 14px;
  }
  
  .send-btn {
    padding: 10px 16px;
    font-size: 13px;
  }
  
  .input-actions button {
    width: 32px;
    height: 32px;
  }
  
  /* 表情面板 */
  .emoji-picker {
    width: calc(100% - 24px);
    left: 12px;
    bottom: 70px;
  }
  
  .emoji-list {
    grid-template-columns: repeat(7, 1fr);
  }
  
  /* 图片消息 */
  .message-bubble img {
    max-width: 200px;
  }
}

@media (max-width: 480px) {
  .navbar {
    padding: 0 12px;
    height: 50px;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .logo-icon {
    width: 28px;
    height: 28px;
  }
  
  .logo-text {
    display: none;
  }
  
  .page-title {
    font-size: 14px;
  }
  
  .nav-btn {
    padding: 5px 10px;
    font-size: 11px;
  }
  
  .chat-container {
    margin-top: 50px;
    height: calc(100vh - 50px);
  }
  
  .conversation-header h3 {
    font-size: 15px;
  }
  
  .conversation-avatar {
    width: 40px;
    height: 40px;
  }
  
  .conversation-name {
    font-size: 13px;
  }
  
  .conversation-last-msg {
    font-size: 11px;
  }
  
  .conversation-time {
    font-size: 10px;
  }
  
  .message-bubble {
    max-width: 80%;
    font-size: 13px;
  }
  
  .emoji-list {
    grid-template-columns: repeat(6, 1fr);
  }
  
  .emoji-item {
    width: 28px;
    height: 28px;
    font-size: 18px;
  }
}
</style>
