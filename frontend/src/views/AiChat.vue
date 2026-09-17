<template>
  <div class="ai-chat-page">
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">
        <svg class="logo-icon" viewBox="0 0 1024 1024" fill="currentColor">
          <path d="M512 1024c282.771692 0 512-229.228308 512-512S794.771692 0 512 0 0 229.228308 0 512s229.228308 512 512 512z m0-59.076923C261.858462 964.923077 59.076923 762.141538 59.076923 512S261.858462 59.076923 512 59.076923s452.923077 202.781538 452.923077 452.923077-202.781538 452.923077-452.923077 452.923077z"/>
          <path d="M464.945231 748.642462c15.399385 3.042462 31.133538 4.588308 47.054769 4.588307 133.228308 0 241.230769-108.002462 241.230769-241.230769S645.228308 270.769231 512 270.769231 270.769231 378.771692 270.769231 512c0 15.921231 1.545846 31.655385 4.588307 47.054769a24.615385 24.615385 0 0 0 48.295385-9.550769A193.053538 193.053538 0 0 1 320 512c0-106.043077 85.956923-192 192-192S704 405.956923 704 512 618.043077 704 512 704c-12.701538 0-25.245538-1.230769-37.494154-3.652923a24.615385 24.615385 0 1 0-9.550769 48.295385z"/>
          <path d="M512 512m-78.769231 0a78.769231 78.769231 0 1 0 157.538462 0 78.769231 78.769231 0 1 0-157.538462 0Z"/>
          <path d="M510.385231 498.294154C396.465231 543.123692 320 653.351385 320 777.846154a24.615385 24.615385 0 1 0 49.230769 0 251.145846 251.145846 0 0 1 159.182769-233.737846 24.615385 24.615385 0 0 0-18.018461-45.814154z"/>
        </svg>
        <span class="logo-text">EasyJob</span>
      </div>
      <div class="page-title">智能助手</div>
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/')">返回首页</button>
      </div>
    </nav>

    <!-- 主容器 -->
    <div class="chat-container">
      <!-- 左侧会话列表 -->
      <div :class="['conversation-sidebar', { hidden: !showSidebar }]">
        <div class="sidebar-header">
          <h3>对话历史</h3>
          <button class="new-chat-btn" @click="createNewConversation">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
            </svg>
            新对话
          </button>
        </div>
        
        <div class="conversation-list" ref="conversationListRef" @scroll="handleConversationScroll">
          <div 
            v-for="conv in conversations" 
            :key="conv.conversationId"
            :class="['conversation-item', { active: currentConversationId === conv.conversationId }]"
            @click="switchConversation(conv)"
          >
            <div class="conv-icon">
              <svg viewBox="0 0 1024 1024" width="18" height="18">
                <path fill="currentColor" d="M535.552 796.444444H739.555556q70.712889 0 120.661333-50.005333Q910.222222 696.490667 910.222222 625.777778V341.333333q0-70.712889-50.005333-120.661333Q810.268444 170.666667 739.555556 170.666667H284.444444q-70.712889 0-120.661333 50.005333Q113.777778 270.620444 113.777778 341.333333v284.444445q0 70.712889 50.005333 120.661333Q213.731556 796.444444 284.444444 796.444444h13.084445q4.266667 8.533333 9.898667 16.497778 21.219556 30.151111 55.751111 44.487111 34.531556 14.279111 70.883555 7.964445 39.310222-6.826667 68.152889-35.612445L535.552 796.444444zM739.555556 682.666667H512a56.888889 56.888889 0 0 0-40.220444 16.668444l-50.005334 50.005333q-6.485333 6.485333-15.018666 2.958223Q398.222222 748.771556 398.222222 739.555556a56.888889 56.888889 0 0 0-56.888889-56.888889H284.444444q-23.552 0-40.220444-16.668445T227.555556 625.777778V341.333333q0-23.552 16.668444-40.220444T284.444444 284.444444h455.111112q23.552 0 40.220444 16.668445T796.444444 341.333333v284.444445q0 23.552-16.668444 40.220444T739.555556 682.666667zM341.333333 540.444444a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z"/>
              </svg>
            </div>
            <div class="conv-info">
              <div class="conv-title">{{ conv.title || '新对话' }}</div>
              <div class="conv-time">{{ formatTime(conv.updateTime) }}</div>
            </div>
            <button class="delete-btn" @click.stop="deleteConversation(conv.conversationId)">
              <svg viewBox="0 0 24 24" width="16" height="16">
                <path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
              </svg>
            </button>
          </div>
          
          <div v-if="conversations.length === 0 && !loadingConversations" class="no-conversations">
            暂无对话历史
          </div>
          <div v-if="loadingConversations" class="loading-conversations">
            加载中...
          </div>
          <div v-if="loadingMoreConversations" class="loading-conversations">
            加载更多...
          </div>
        </div>
      </div>

      <!-- 右侧聊天区域 -->
      <div class="chat-main">
        <!-- 移动端返回按钮 -->
        <button class="mobile-back-btn" @click="showSidebar = true" v-if="!showSidebar">
          <svg viewBox="0 0 24 24" width="24" height="24">
            <path fill="currentColor" d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/>
          </svg>
        </button>

        <!-- 加载会话消息中 -->
        <div v-if="loadingMessages" class="welcome-area">
          <div class="typing-indicator" style="transform: scale(1.5);">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p style="color: #909399; margin-top: 20px;">加载中...</p>
        </div>

        <!-- 欢迎区域 -->
        <div v-else-if="messages.length === 0" class="welcome-area">
          <div class="welcome-inner">
            <div class="welcome-eyebrow">EasyJob · 智能助手</div>
            <h2 class="welcome-title">有什么可以帮你的？</h2>
            <p class="welcome-desc">搜索文章、撰写草稿、联网检索。</p>

            <!-- 快捷问题 -->
            <div class="quick-questions">
              <div
                v-for="(q, index) in quickQuestions"
                :key="index"
                class="quick-question-item"
                @click="sendQuickQuestion(q)"
              >
                <span class="qq-text">{{ q }}</span>
                <svg class="qq-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M7 17L17 7M17 7H9M17 7V15"/>
                </svg>
              </div>
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-else class="message-list" ref="messageListRef" @scroll="handleMessageScroll">
          <div 
            v-for="(msg, index) in messages" 
            :key="index"
            :class="['message-item', msg.role]"
          >
            <div class="message-avatar">
              <svg v-if="msg.role === 'assistant'" viewBox="0 0 1024 1024" fill="currentColor">
                <path d="M966.392 448.741L851.745 249.689a27.039 27.039 0 0 0-23.431-13.544h-42.126l-78.386-135.769a27.04 27.04 0 0 0-23.417-13.52H454.539a27.039 27.039 0 0 0-23.4 13.49l-20.99 36.249-156.729 0.025a27.04 27.04 0 0 0-23.413 13.52L115.084 349.191a27.041 27.041 0 0 0 0 27.04l20.925 36.243-78.386 135.769a27.041 27.041 0 0 0 0 27.04l114.923 199.052a27.04 27.04 0 0 0 23.417 13.52h41.85l78.386 135.769a27.04 27.04 0 0 0 23.417 13.52h229.845a27.04 27.04 0 0 0 23.417-13.52l20.925-36.243h156.773a27.04 27.04 0 0 0 23.417-13.52l114.923-199.052a27.041 27.041 0 0 0 0-27.04l-20.925-36.243 78.386-135.769a27.04 27.04 0 0 0 0.015-27.016zM767.96 557.282l-219.424-0.026 82.291-142.529a4.517 4.517 0 0 0 0-4.507L462.345 118.403h219.439l84.889 147.035 0.003 0.004 84.888 147.032-83.604 144.808z m62.68-90.538h104.516l-78.388 135.767L804.51 512l26.13-45.256z m-208.921-54.27L540.73 552.748 517.204 512l27.429-47.509c0.031-0.054 0.042-0.115 0.07-0.17 0.125-0.24 0.228-0.49 0.31-0.753 0.028-0.091 0.062-0.179 0.084-0.271 0.082-0.341 0.139-0.693 0.139-1.059a4.46 4.46 0 0 0-0.139-1.059c-0.022-0.092-0.056-0.181-0.084-0.272a4.565 4.565 0 0 0-0.31-0.753c-0.029-0.055-0.039-0.116-0.07-0.17L429.711 260.932a4.509 4.509 0 0 0-3.904-2.254h-49.653l78.384-135.768 167.181 289.564zM365.744 258.678h-52.255l-52.259-90.514 156.787-0.024-52.273 90.538z m-62.664 0h-49.655a4.508 4.508 0 0 0-3.904 2.254l-82.29 142.528-23.526-40.748 109.719-190.038 49.656 86.004z m-131.946 156.05l84.891-147.036h54.856l0.009 0.001 0.009-0.001h112.307l109.718 190.039H368.347a4.508 4.508 0 0 0-3.904 2.254L195.961 751.802 86.244 561.763l84.89-147.035z m199.814 52.016h161.975l-23.527 40.749h-54.859c-0.037 0-0.073 0.014-0.11 0.015a4.484 4.484 0 0 0-2.044 0.548c-0.08 0.044-0.154 0.093-0.231 0.142a4.454 4.454 0 0 0-0.652 0.499c-0.068 0.063-0.139 0.122-0.203 0.189a4.439 4.439 0 0 0-0.662 0.86L335.712 708.799a4.515 4.515 0 0 0 0 4.506l24.828 43.003H203.769l167.179-289.564z m-5.205 298.578l26.129 45.257-52.258 90.511-78.384-135.768h104.513z m31.334 54.272l24.826 43.001a4.508 4.508 0 0 0 3.904 2.253h164.579l-23.524 40.749h-219.44l49.655-86.003z m31.331 36.241L344.82 711.052l109.719-190.038 82.288 142.528a4.508 4.508 0 0 0 3.904 2.253h336.963l-109.718 190.04H428.408z m114.923-199.053l-80.987-140.276h47.055l27.427 47.51c0.044 0.076 0.103 0.137 0.152 0.21 0.087 0.134 0.177 0.264 0.279 0.389 0.095 0.115 0.197 0.221 0.301 0.326 0.1 0.1 0.2 0.197 0.311 0.288 0.13 0.107 0.266 0.201 0.406 0.292 0.069 0.046 0.128 0.102 0.2 0.144 0.034 0.02 0.073 0.025 0.107 0.044 0.314 0.17 0.64 0.315 0.984 0.406 0.035 0.01 0.071 0.009 0.107 0.018 0.302 0.072 0.61 0.11 0.92 0.119 0.044 0.001 0.088 0.017 0.132 0.017 0.051 0 0.099-0.018 0.15-0.019 0.062 0.002 0.119 0.018 0.18 0.018l229.505 0.027a4.509 4.509 0 0 0 3.904-2.253l24.841-43.027 53.556 92.759 0.001 0.003 24.83 43.005H543.331z m292.512-199.051l24.828-43.003a4.517 4.517 0 0 0 0-4.507l-82.289-142.529h47.325l109.457 190.039h-99.321z"/>
              </svg>
              <img v-else :src="getAvatarUrl(userAvatar)" @error="handleAvatarError">
            </div>
            <div class="message-content">
              <!-- 用户发送的图片（点击可放大） -->
              <el-image 
                v-if="msg.image" 
                :src="msg.image" 
                :preview-src-list="[msg.image]"
                class="message-image" 
                alt="用户图片"
                fit="contain"
                :preview-teleported="true"
              />
              <!-- 执行进度步骤条 -->
              <div v-if="msg.progressSteps && msg.progressSteps.length > 0 && !msg.content" class="progress-steps">
                <div 
                  v-for="step in msg.progressSteps" 
                  :key="step.key"
                  :class="['progress-step', step.status]"
                >
                  <div class="step-indicator">
                    <svg v-if="step.status === 'done'" viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                    </svg>
                    <div v-else-if="step.status === 'active'" class="step-spinner"></div>
                    <div v-else class="step-dot"></div>
                  </div>
                  <span class="step-label">{{ step.label }}</span>
                  <span v-if="step.detail" class="step-detail">{{ step.detail }}</span>
                </div>
              </div>
              <!-- 消息为空且无进度时显示加载动画 -->
              <div v-if="msg.role === 'assistant' && !msg.content && (!msg.progressSteps || msg.progressSteps.length === 0)" class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <div v-else-if="msg.content" class="message-bubble" :class="{ 'draft-bubble': msg.isDraft }">
                <div v-if="msg.isDraft" class="draft-badge">
                  <svg viewBox="0 0 1024 1024" width="14" height="14" fill="currentColor"><path d="M864 96H288c-17.7 0-32 14.3-32 32v64h-64c-17.7 0-32 14.3-32 32v640c0 17.7 14.3 32 32 32h576c17.7 0 32-14.3 32-32v-64h64c17.7 0 32-14.3 32-32V128c0-17.7-14.3-32-32-32zM736 832H224V256h512v576zm128-128H800V224c0-17.7-14.3-32-32-32H320v-64h544v576z"/></svg>
                  草稿预览
                </div>
                <div v-html="renderMarkdown(msg.content)"></div>
              </div>
              <!-- 流式生成中指示器 -->
              <div v-if="msg.role === 'assistant' && streaming && index === messages.length - 1 && msg.content" class="generating-indicator">
                <div class="generating-dot-pulse"></div>
                <span>正在生成...</span>
              </div>
              <!-- Human-in-the-loop 审批区域 -->
              <div v-if="msg.interrupted" class="interrupt-actions">
                <div class="interrupt-hint">{{ msg.interruptPayload?.message || '需要您确认后继续' }}</div>
                <div class="interrupt-buttons">
                  <button class="interrupt-btn approve" @click="handleResume('approve', msg)" :disabled="resuming">确认</button>
                  <button class="interrupt-btn reject" @click="handleResume('reject', msg)" :disabled="resuming">拒绝</button>
                </div>
              </div>
              <!-- HITL 草稿已保存链接：approve 后显示 -->
              <div v-if="msg.draftArticleId" class="draft-link" @click="editDraft(msg.draftArticleId)">
                <svg class="draft-link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                </svg>
                <span class="draft-link-text">
                  已保存至草稿箱
                  <span v-if="msg.draftTitle" class="draft-link-title">《{{ msg.draftTitle }}》</span>
                </span>
                <span class="draft-link-action">
                  编辑草稿
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M7 17L17 7M17 7H9M17 7V15"/>
                  </svg>
                </span>
              </div>
              <!-- 文章卡片列表 -->
              <div v-if="msg.articles && msg.articles.length > 0" class="article-cards">
                <div 
                  v-for="article in msg.articles" 
                  :key="article.articleId"
                  class="article-card"
                  @click="openArticle(article.articleId)"
                >
                  <div class="card-cover" v-if="article.coverImage">
                    <img :src="getThumbUrl(article.coverImage) || article.coverImage" :alt="article.title" @error="handleArticleCoverError($event, article.coverImage)" />
                  </div>
                  <div class="card-info">
                    <div class="card-title">{{ article.title }}</div>
                    <div class="card-summary" v-if="article.summary">{{ article.summary }}</div>
                    <div class="card-meta">
                      <span class="author">{{ article.authorName || 'EasyJob 用户' }}</span>
                      <span class="stats">
                        <span class="stat-item">
                          <svg viewBox="0 0 1024 1024" width="12" height="12" fill="currentColor">
                            <path d="M675.328 117.717333A425.429333 425.429333 0 0 0 512 85.333333C276.352 85.333333 85.333333 276.352 85.333333 512s191.018667 426.666667 426.666667 426.666667 426.666667-191.018667 426.666667-426.666667c0-56.746667-11.093333-112-32.384-163.328a21.333333 21.333333 0 0 0-39.402667 16.341333A382.762667 382.762667 0 0 1 896 512c0 212.074667-171.925333 384-384 384S128 724.074667 128 512 299.925333 128 512 128c51.114667 0 100.8 9.984 146.986667 29.12a21.333333 21.333333 0 0 0 16.341333-39.402667zM456.704 305.92C432.704 289.152 405.333333 303.082667 405.333333 331.797333v360.533334c0 28.586667 27.541333 42.538667 51.370667 25.856l252.352-176.768c21.76-15.253333 21.632-43.541333 0-58.709334l-252.373333-176.768z m-8.597333 366.72V351.466667l229.269333 160.597333-229.269333 160.597333z"/>
                          </svg>
                          {{ article.viewCount || 0 }}
                        </span>
                        <span class="stat-item">
                          <svg viewBox="0 0 1024 1024" width="12" height="12" fill="currentColor">
                            <path d="M939.358251 423.424662c-23.01825-37.252439-62.924121-60.779272-107.019409-63.209624-2.755764-0.38681-5.510504-0.579191-8.347109-0.579191l-152.202471-0.121773c6.649444-28.975938 10.015098-58.653865 10.015098-88.657202 0-28.223808-3.213181-57.139372-9.556657-85.952604-0.447185-2.043542-1.098008-4.006244-1.932002-5.866614-15.820314-57.302077-67.37755-96.841605-127.282918-96.841605-72.827679 0-132.081201 59.254545-132.081201 132.081201 0 3.334955 0.132006 6.66991 0.406253 10.015098-2.196015 57.211003-32.108279 109.947088-80.269162 141.363611-14.447037 9.42465-18.524912 28.773324-9.099239 43.220361 9.414417 14.437827 28.752858 18.535145 43.220361 9.099239 65.811892-42.925648 106.429984-115.325585 108.656699-193.684234 0.030699-1.332345-0.010233-2.663666-0.14224-3.996011-0.203638-2.012843-0.304945-4.016477-0.304945-6.019087 0-38.381146 31.233352-69.614497 69.614497-69.614497 32.57593 0 60.474326 22.204721 67.824735 53.997821 0.356111 1.534959 0.823761 3.019777 1.402953 4.453429 4.696975 22.814612 7.076162 45.579081 7.076162 67.743894 0 37.485753-6.222725 74.352405-18.494213 109.592001-3.324722 9.546424-1.819438 20.111037 4.02671 28.345582 5.856381 8.245801 15.332197 13.146415 25.448602 13.156648l193.226816 0.101307c1.423419 0.264013 2.857071 0.426719 4.300956 0.477884 24.116257 0.9967 45.935192 13.614066 58.603723 34.090423 7.838525 12.31242 11.438517 26.800389 10.431583 41.939181-0.080841 0.945535-0.121773 1.911536-0.11154 2.877537 0 0.854461 0.040932 1.697665 0.11154 2.53166 0.010233 0.335644-0.030699 0.661056-0.11154 0.976234-0.101307 0.376577-0.193405 0.772596-0.284479 1.159406l-74.972529 330.391802c-0.914836 1.281179-1.738597 2.6432-2.449795 4.046153-5.937223 11.762905-14.660908 21.48329-25.346271 28.172643-10.746762 6.812149-23.059182 10.614755-35.757388 11.06194-0.854461-0.061398-513.766226-0.224104-513.766226-0.224104-0.467651-0.020466-0.935302-0.030699-1.402953-0.030699 0 0-111.01542 0.172939-112.718201 0.457418-1.932002 0-3.446495-1.50426-3.446495-3.415796l0.299829-416.334173c0-1.901303 1.545192-3.446495 3.01466-3.456728l1.245364 0.121773c1.174756 0.132006 2.653433 0.284479 3.52836 0.193405l83.82822-0.222057 0 339.367221c0 17.253966 13.979386 31.233352 31.233352 31.233352s31.233352-13.979386 31.233352-31.233352L281.009092 435.350273c0-1.778506 0-8.631588 0-10.411117 0-17.253966-13.979386-30.928407-31.233352-30.928407-1.50426 0-117.547183 0.304945-119.402437 0.304945-36.34272 0-65.913199 29.566386-65.913199 65.893756l-0.299829 416.334173c0 36.337603 29.571503 65.902966 65.913199 65.902966 2.541893 0 111.406323-0.457418 111.406323-0.457418 0.457418 0.020466 0.925069 0.030699 1.382487 0.030699 0 0 511.458671 0.274246 512.505513 0.274246 25.469068 0 50.296523-7.197936 71.647807-20.73116 19.612687-12.281721 35.777855-29.881564 46.839795-50.967812 3.660366-5.622044 6.435573-11.875468 8.256034-18.615986 0.11154-0.416486 0.213871-0.823761 0.304945-1.240247l74.881454-330.340637c1.596358-6.212492 2.257413-12.586666 2.00261-18.992563C960.892707 473.366098 953.948551 446.331371 939.358251 423.424662z"/>
                          </svg>
                          {{ article.likeCount || 0 }}
                        </span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <!-- 图片预览（支持多图） -->
          <div v-if="selectedImages.length > 0 || uploadingImage" class="image-preview-list">
            <div v-for="(img, index) in selectedImages" :key="index" class="image-preview-item">
              <img :src="img.preview" alt="预览" />
              <button class="remove-image-btn" @click="removeImage(index)">
                <svg viewBox="0 0 24 24" width="16" height="16">
                  <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                </svg>
              </button>
            </div>
            <!-- 上传中的图片预览 -->
            <div v-if="uploadingImage" class="image-preview-item uploading">
              <img v-if="uploadingPreview" :src="uploadingPreview" alt="上传中" />
              <div class="upload-progress-overlay">
                <div class="upload-progress-bar" :style="{ width: uploadProgress + '%' }"></div>
                <span class="upload-progress-text">{{ uploadProgress }}%</span>
              </div>
            </div>
          </div>
          <div class="input-wrapper">
            <!-- 图片上传按钮 -->
            <button class="upload-btn" @click="triggerImageUpload" :disabled="loading || uploadingImage">
              <svg viewBox="0 0 1024 1024" width="22" height="22">
                <path fill="currentColor" d="M853.161077 892.549156 362.595248 892.549156l-209.432916-0.413416c-0.605797-0.001023-1.210571-0.031722-1.813299-0.092098-24.848944-2.484587-47.825238-14.060227-64.696488-32.594349-16.990976-18.665105-26.349111-42.85504-26.349111-68.112284L60.303434 264.62596c0-55.80805 45.403073-101.211123 101.211123-101.211123l691.645496 0c55.80805 0 101.2101 45.403073 101.2101 101.211123l0 225.51315c0 0.275269-0.00614 0.551562-0.01842 0.825808-0.021489 0.494257-1.971911 51.723012 15.481599 85.46244 4.716418 9.118682 1.14815 20.335141-7.970532 25.052582-9.116635 4.714372-20.335141 1.149173-25.052582-7.970532-21.300119-41.176818-19.844977-97.642854-19.618826-103.738689L917.191392 264.62596c0-35.307134-28.724205-64.031339-64.031339-64.031339L161.51558 200.594621c-35.307134 0-64.031339 28.724205-64.031339 64.031339l0 526.71105c0 32.755008 24.320918 59.957557 56.717769 63.61997l208.4311 0.412392 490.528989 0c35.307134 0 64.031339-28.725228 64.031339-64.032362l-0.382717-93.676519c-0.104377-1.749854-1.587148-19.548218-19.549242-42.499953-0.050142-0.063445-0.098237-0.125867-0.147356-0.190335L875.401614 626.481358 758.174726 471.362464c-0.415462-0.550539-38.995129-50.852178-86.271876-45.534056-38.335097 4.314259-75.954903 45.163619-108.789729 118.131491-17.615193 39.141462-34.650171 68.26885-52.082192 89.046059-17.607006 20.985964-35.679617 33.519418-55.251372 38.316677-43.422975 10.638291-81.049944-18.99461-120.886231-50.372248l-5.057179-3.980661c-46.555315-36.57808-68.750827-28.223808-158.330028 59.60247-7.330966 7.187703-19.101033 7.071046-26.288736-0.25992-7.187703-7.330966-7.071046-19.101033 0.25992-26.287713 46.658669-45.74588 77.544097-72.726372 107.085924-84.282568 33.357735-13.048177 64.274886-6.266727 100.242052 21.99392l5.092995 4.00829c33.9226 26.719548 63.219857 49.795103 89.028663 43.466977 25.618471-6.279007 53.30095-42.114167 82.279958-106.508779 39.139415-86.97591 85.837994-134.027529 138.79716-139.849118 68.454068-7.515161 117.823476 57.404408 119.891578 60.171428l117.122511 154.980747 21.599947 28.343535c26.276457 33.630958 27.333532 61.638849 27.367301 64.72514 0.001023 0.042979 0.001023 0.084934 0.001023 0.127913l0.38374 94.059236C954.371176 847.146083 908.969127 892.549156 853.161077 892.549156z"/>
                <path fill="currentColor" d="M312.328401 446.967868c-42.324968 0-76.759221-34.434254-76.759221-76.759221s34.434254-76.759221 76.759221-76.759221 76.759221 34.434254 76.759221 76.759221S354.654392 446.967868 312.328401 446.967868zM312.328401 330.628186c-21.824051 0-39.579437 17.755386-39.579437 39.579437s17.755386 39.579437 39.579437 39.579437 39.579437-17.755386 39.579437-39.579437S334.153476 330.628186 312.328401 330.628186z"/>
              </svg>
            </button>
            <input 
              type="file" 
              ref="imageInput" 
              accept="image/*" 
              style="display: none" 
              @change="handleImageSelect"
            />
            <textarea 
              v-model="userInput"
              placeholder="输入你的问题，按 Enter 发送，Shift + Enter 换行，支持图片"
              @keydown.enter.exact.prevent="sendMessage"
              @keydown.enter.shift.exact="newLine"
              rows="1"
              ref="inputRef"
              :disabled="loading"
            ></textarea>
            <button 
              v-if="streaming"
              class="stop-btn" 
              @click="handleCancel"
              title="暂停生成"
            >
              <svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
            </button>
            <button 
              v-else
              class="send-btn" 
              @click="sendMessage" 
              :disabled="(!userInput.trim() && selectedImages.length === 0) || loading"
            >
              <svg v-if="!loading" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
              <span v-else class="loading-spinner"></span>
            </button>
          </div>
          <div class="input-tips">
            <span class="tip-text">回复仅供参考，请核实重要信息</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 登录弹窗 -->
  <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
    <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
  </el-dialog>
  <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
    <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import LoginForm from '@/components/LoginForm.vue'
import RegisterForm from '@/components/RegisterForm.vue'
import request from '@/utils/request'
import { getThumbUrl } from '@/utils/image'
import { eventBus, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'

// marked 配置
marked.setOptions({
  breaks: true,
  gfm: true
})

const router = useRouter()

// 用户信息
const userAvatar = ref(localStorage.getItem('avatar') || '')

// 会话状态
const conversations = ref<any[]>([])
const savedConvId = localStorage.getItem('ai_conversation_id')
const currentConversationId = ref<string | null>(savedConvId && savedConvId !== 'null' ? savedConvId : null)
const loadingConversations = ref(false)
const loadingMoreConversations = ref(false)  // 加载更多中
const hasMoreConversations = ref(true)  // 是否还有更多
const conversationListRef = ref<HTMLElement>()  // 会话列表容器
const showSidebar = ref(true)

// 消息状态
interface ArticleCard {
  articleId: string  // 雪花ID用string避免精度丢失
  title: string
  coverImage: string
  authorName: string
  summary: string
  viewCount: number
  likeCount: number
}

interface ProgressStep {
  key: string       // planner | dispatcher | synthesizer
  label: string     // 显示文本
  status: 'pending' | 'active' | 'done'
  detail?: string   // 额外信息（如 Worker 列表）
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  image?: string | null
  articles?: ArticleCard[]  // 文章卡片数据
  progressSteps?: ProgressStep[]  // 执行进度步骤
  interrupted?: boolean  // 是否被 interrupt 暂停
  interruptPayload?: Record<string, any>  // interrupt 携带的数据（如草稿内容）
  isDraft?: boolean  // 当前内容是否为草稿
  draftArticleId?: string  // HITL 草稿确认后关联的 article_info.article_id，用 string 避免 JS 精度丢失
  draftTitle?: string  // 草稿标题，显示在"编辑草稿"按钮旁边
}
const messages = ref<ChatMessage[]>([])
const userInput = ref('')
const loading = ref(false)
const streaming = ref(false)  // AI正在流式生成中
const resuming = ref(false)   // Human-in-the-loop 恢复中
let currentAbortController: AbortController | null = null  // 用于中断SSE流
const loadingMessages = ref(false)  // 切换会话时的加载状态

// 自动跟随滚动到底部（用户手动往上滚后暂停，回到底部附近恢复）
const messageListRef = ref<HTMLElement>()
const inputRef = ref<HTMLTextAreaElement>()

// 自动跟随滚动到底部（用户手动往上滚后暂停，回到底部附近恢复）
// 阈值：距离底部 80px 以内视为"在底部"
const autoScrollToBottom = ref(true)
const SCROLL_BOTTOM_THRESHOLD = 80

// 图片相关状态
interface SelectedImage {
  file: File
  preview: string
  path: string  // 上传后的服务器路径
}
const selectedImages = ref<SelectedImage[]>([])  // 支持多图
const imageInput = ref<HTMLInputElement>()
const uploadingImage = ref(false)  // 图片上传中状态
const uploadProgress = ref(0)  // 上传进度 0-100
const uploadingPreview = ref('')  // 上传中图片的预览URL

// 快捷问题
const quickQuestions = [
  '整理几篇 Spring Boot 入门文章',
  '最近有哪些值得关注的技术文章',
  '帮我写一篇聊聊前端工程化的草稿',
  '用简明语言解释一下 RAG'
]

// 加载会话列表（首次加载）
async function loadConversations() {
  loadingConversations.value = true
  hasMoreConversations.value = true
  try {
    const res = await request.get('/agent/conversations', { params: { limit: 20 } })
    if (res.code === 200 && res.data) {
      conversations.value = res.data
      // 返回数量小于limit说明没有更多了
      hasMoreConversations.value = res.data.length >= 20
    }
  } catch (error) {
    console.error('加载会话列表失败:', error)
  } finally {
    loadingConversations.value = false
  }
}

// 加载更多会话（滚动触发）
async function loadMoreConversations() {
  if (loadingMoreConversations.value || !hasMoreConversations.value || conversations.value.length === 0) return
  
  loadingMoreConversations.value = true
  try {
    // 获取最后一条的 updateTime 和 conversationId 作为复合游标
    const lastConv = conversations.value[conversations.value.length - 1]
    const lastUpdateTime = lastConv.updateTime
    const lastId = lastConv.conversationId
    
    const res = await request.get('/agent/conversations', { params: { lastUpdateTime, lastId, limit: 20 } })
    if (res.code === 200 && res.data) {
      conversations.value.push(...res.data)
      hasMoreConversations.value = res.data.length >= 20
    }
  } catch (error) {
    console.error('加载更多会话失败:', error)
  } finally {
    loadingMoreConversations.value = false
  }
}

// 会话列表滚动事件
function handleConversationScroll() {
  const el = conversationListRef.value
  if (!el) return
  
  // 距离底部小于50px时触发加载
  const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  if (isNearBottom) {
    loadMoreConversations()
  }
}

// 创建新会话
function createNewConversation() {
  currentConversationId.value = null
  localStorage.removeItem('ai_conversation_id')
  messages.value = []
  if (window.innerWidth <= 768) {
    showSidebar.value = false
  }
}

// 切换会话
async function switchConversation(conv: any) {
  // 同一个会话且消息已加载，无需重复请求
  if (currentConversationId.value === conv.conversationId && messages.value.length > 0) {
    if (window.innerWidth <= 768) {
      showSidebar.value = false
    }
    return
  }
  
  currentConversationId.value = conv.conversationId
  localStorage.setItem('ai_conversation_id', conv.conversationId)
  messages.value = []
  loadingMessages.value = true
  
  if (window.innerWidth <= 768) {
    showSidebar.value = false
  }
  
  try {
    const res = await request.get(`/agent/conversations/${conv.conversationId}/messages`)
    if (res.code === 200 && res.data) {
      messages.value = res.data.map((msg: any) => ({
        role: msg.role,
        content: msg.content,
        image: msg.imagePaths && msg.imagePaths.length > 0 ? `/uploads/${msg.imagePaths[0]}` : null,
        articles: msg.articleCards || [],
        draftArticleId: msg.draftArticleId || undefined,
      }))
    }
  } catch (error) {
    console.error('加载会话消息失败:', error)
  } finally {
    loadingMessages.value = false
    // 等待DOM更新后再滚动到底部
    nextTick(() => {
      scrollToBottom(true)
    })
  }
}

// 删除会话
async function deleteConversation(conversationId: string) {
  try {
    const res = await request.delete(`/agent/conversations/${conversationId}`)
    if (res.code === 200) {
      conversations.value = conversations.value.filter(c => c.conversationId !== conversationId)
      if (currentConversationId.value === conversationId) {
        createNewConversation()
      }
      ElMessage.success('删除成功')
    }
  } catch (error) {
    console.error('删除会话失败:', error)
    ElMessage.error('删除失败')
  }
}

// 图片上传
function triggerImageUpload() {
  imageInput.value?.click()
}

function handleImageSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  
  if (file.size > 15 * 1024 * 1024) {
    ElMessage.warning('图片大小不能超过15MB')
    return
  }
  
  // 限制最多3张图片
  if (selectedImages.value.length >= 3) {
    ElMessage.warning('最多只能上传3张图片')
    return
  }
  
  // 先上传图片到服务器
  uploadImage(file)
  
  // 清空input，允许重复选择同一文件
  target.value = ''
}

// 上传图片到服务器
async function uploadImage(file: File) {
  uploadingImage.value = true
  uploadProgress.value = 0
  uploadingPreview.value = URL.createObjectURL(file)
  
  const formData = new FormData()
  formData.append('file', file)
  
  try {
    const token = localStorage.getItem('token')
    
    // 使用 XMLHttpRequest 获取上传进度
    const result = await new Promise<any>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          uploadProgress.value = Math.round((event.loaded / event.total) * 100)
        }
      }
      
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else if (xhr.status === 401) {
          reject(new Error('登录已过期'))
        } else {
          reject(new Error(`上传失败: ${xhr.status}`))
        }
      }
      
      xhr.onerror = () => reject(new Error('网络错误'))
      xhr.ontimeout = () => reject(new Error('上传超时'))
      
      xhr.open('POST', '/api/file/upload-ai-chat')
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.timeout = 60000  // 60秒超时
      xhr.send(formData)
    })
    
    if (result.code === 200) {
      selectedImages.value.push({
        file,
        preview: uploadingPreview.value,
        path: result.data.path
      })
      uploadingPreview.value = ''  // 清空，避免重复显示
    } else {
      URL.revokeObjectURL(uploadingPreview.value)
      ElMessage.error('图片上传失败: ' + result.message)
    }
  } catch (error: any) {
    console.error('图片上传失败:', error)
    URL.revokeObjectURL(uploadingPreview.value)
    ElMessage.error(error.message || '图片上传失败，请重试')
  } finally {
    uploadingImage.value = false
    uploadProgress.value = 0
    uploadingPreview.value = ''
  }
}

function removeImage(index: number) {
  selectedImages.value.splice(index, 1)
}

// 发送消息
async function sendMessage() {
  const content = userInput.value.trim()
  if (!content && selectedImages.value.length === 0) return
  if (loading.value || uploadingImage.value) return
  
  // 添加用户消息（含图片预览）
  const userMsg: ChatMessage = {
    role: 'user',
    content: content,
    image: selectedImages.value.length > 0 ? selectedImages.value[0].preview : null  // 显示第一张预览
  }
  messages.value.push(userMsg)
  
  // 暂存图片路径列表，清空输入
  const imagePaths = selectedImages.value.map(img => img.path)
  userInput.value = ''
  selectedImages.value = []
  loading.value = true
  scrollToBottom(true)
  
  // 准备AI回复占位
  const aiMessage: ChatMessage = {
    role: 'assistant',
    content: ''
  }
  messages.value.push(aiMessage)
  // 通过数组索引引用，确保Vue响应式更新
  const aiMsgIndex = messages.value.length - 1
  
  try {
    streaming.value = true
    await streamChat(content, imagePaths, aiMsgIndex)
  } catch (error: any) {
    // 用户主动取消不算错误
    if (error.name === 'AbortError') return
    console.error('发送消息失败:', error)
    messages.value[aiMsgIndex].content = '抱歉，发生了错误，请稍后重试。'
    ElMessage.error(error.message || '请求失败')
  } finally {
    loading.value = false
    streaming.value = false
    currentAbortController = null
    scrollToBottom()
  }
}

// SSE流式接收，标准SSE解析
async function streamChat(message: string, imagePaths: string[], aiMsgIndex: number) {
  const token = localStorage.getItem('token')
  currentAbortController = new AbortController()
  
  const body: Record<string, any> = {
    message: message || '',
    conversationId: currentConversationId.value
  }
  if (imagePaths.length > 0) {
    body.imagePaths = imagePaths
  }
  
  const response = await fetch('/api/agent/chat/stream', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify(body),
    signal: currentAbortController.signal
  })
  
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`)
  }
  
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    
    // 标准SSE格式：事件之间用 \n\n 分隔
    // 每个事件可能包含多个 data: 行，多行 data: 用 \n 拼接还原原始换行
    // 例如后端发送 "## 标题\n内容" 会变成：
    //   data:## 标题\ndata:内容\n\n
    const events = buffer.split('\n\n')
    // 最后一个可能不完整，保留到下次
    buffer = events.pop() || ''
    
    for (const event of events) {
      if (!event.trim()) continue
      
      // 提取所有 data: 行，用 \n 拼接还原原始内容中的换行
      const dataLines: string[] = []
      for (const line of event.split('\n')) {
        if (line.startsWith('data:')) {
          dataLines.push(line.substring(5))
        }
      }
      if (dataLines.length === 0) continue
      
      const data = dataLines.join('\n')
      if (!data) continue
      
      // 会话ID
      if (data.startsWith('__CONV_ID__:')) {
        const convId = data.substring(12).trim()
        const isNewConversation = !currentConversationId.value
        currentConversationId.value = convId
        localStorage.setItem('ai_conversation_id', convId)
        if (isNewConversation) {
          loadConversations()
        }
        continue
      }
      
      // 文章卡片
      if (data.startsWith('__ARTICLES__:')) {
        try {
          messages.value[aiMsgIndex].articles = JSON.parse(data.substring(13).trim())
        } catch (e) {
          console.error('解析文章卡片失败:', e)
        }
        continue
      }
      
      // 执行进度事件
      if (data.startsWith('__PROGRESS__:')) {
        const progressData = data.substring(13).trim()
        handleProgress(aiMsgIndex, progressData)
        scrollToBottom()
        continue
      }
      
      // Human-in-the-loop 中断事件
      if (data.startsWith('__INTERRUPTED__:')) {
        try {
          const payload = JSON.parse(data.substring(16).trim())
          const msg = messages.value[aiMsgIndex]
          // 显示草稿内容（如果有的话）
          if (payload.draft) {
            msg.content = payload.draft
            msg.isDraft = true
          }
          msg.interrupted = true
          msg.interruptPayload = payload
          // 标记所有进度步骤为done
          if (msg.progressSteps) {
            for (const step of msg.progressSteps) step.status = 'done'
          }
        } catch (e) {
          console.error('解析中断数据失败:', e)
        }
        scrollToBottom()
        continue
      }

      // HITL 草稿已保存到草稿箱事件：把 draftArticleId 挂到当前消息，渲染"编辑草稿"按钮
      if (data.startsWith('__DRAFT_SAVED__:')) {
        try {
          const payload = JSON.parse(data.substring(16).trim())
          const msg = messages.value[aiMsgIndex]
          msg.draftArticleId = payload.draftArticleId
          msg.draftTitle = payload.title || ''
          // approve 通过后，这条消息不再是"草稿预览"态
          msg.isDraft = false
        } catch (e) {
          console.error('解析 __DRAFT_SAVED__ 事件失败:', e)
        }
        continue
      }
      
      // 错误
      if (data.startsWith('[ERROR]')) {
        throw new Error(data.substring(7).trim())
      }
      
      // 终止标记和结尾 JSON（conversationId），跳过
      if (data.trim() === '[DONE]') continue
      if (data.trim().startsWith('{') && data.includes('conversationId')) continue

      // 普通内容：还原被转义的换行符，然后追加
      messages.value[aiMsgIndex].content += data.replace(/\\n/g, '\n')
      scrollToBottom()
    }
  }
  
  // 处理buffer中剩余的不完整事件
  if (buffer.trim()) {
    const dataLines: string[] = []
    for (const line of buffer.split('\n')) {
      if (line.startsWith('data:')) {
        dataLines.push(line.substring(5))
      }
    }
    const data = dataLines.join('\n')
    if (data && !data.startsWith('__') && !data.startsWith('[ERROR]')) {
      messages.value[aiMsgIndex].content += data.replace(/\\n/g, '\n')
    }
  }
}

// Worker 名称映射为中文显示
const workerLabelMap: Record<string, string> = {
  search: '信息检索',
  analysis: '内容分析',
  writing: '写作辅助',
  chat: '对话回复',
  search_then_analysis: '检索并分析'
}

/**
 * 处理执行进度事件
 * 协议格式：
 *   __PROGRESS__:planner                    → Planner 开始执行
 *   __PROGRESS__:dispatcher:search,chat     → Planner 完成，Dispatcher 开始执行
 *   __PROGRESS__:synthesizer                → Dispatcher 完成，开始整理回答
 *   __PROGRESS__:done                       → 全部完成，准备输出内容
 */
function handleProgress(aiMsgIndex: number, progressData: string) {
  const msg = messages.value[aiMsgIndex]
  if (!msg.progressSteps) {
    msg.progressSteps = []
  }

  if (progressData === 'planner') {
    msg.progressSteps = [
      { key: 'planner', label: '理解问题中', status: 'active' }
    ]
  } else if (progressData.startsWith('dispatcher:')) {
    // Planner 完成 → Dispatcher 开始
    const workersStr = progressData.substring(11)
    const workers = workersStr.split(',').filter(Boolean)
    const workerLabels = workers.map(w => workerLabelMap[w.trim()] || w.trim()).join('、')

    const plannerStep = msg.progressSteps.find(s => s.key === 'planner')
    if (plannerStep) {
      plannerStep.label = '理解问题'
      plannerStep.status = 'done'
    }

    msg.progressSteps.push(
      { key: 'dispatcher', label: '处理中', status: 'active', detail: workerLabels }
    )
  } else if (progressData === 'synthesizer') {
    // Dispatcher 完成 → Synthesizer 开始
    const dispatcherStep = msg.progressSteps.find(s => s.key === 'dispatcher')
    if (dispatcherStep) {
      dispatcherStep.label = '处理完成'
      dispatcherStep.status = 'done'
    }

    msg.progressSteps.push(
      { key: 'synthesizer', label: '整理回答中', status: 'active' }
    )
  } else if (progressData === 'done') {
    // 全部完成
    for (const step of msg.progressSteps) {
      step.status = 'done'
      // 去掉"中"字后缀
      if (step.label.endsWith('中')) {
        step.label = step.label.slice(0, -1)
      }
    }
  }
}

// 发送快捷问题
function sendQuickQuestion(question: string) {
  userInput.value = question
  sendMessage()
}

// 暂停生成
async function handleCancel() {
  if (!currentConversationId.value) return
  try {
    // 1. 通知后端取消
    await request.post(`/agent/chat/${currentConversationId.value}/cancel`)
  } catch (e) {
    console.error('暂停失败:', e)
  }
  // 2. 中断前端 SSE 连接
  if (currentAbortController) {
    currentAbortController.abort()
    currentAbortController = null
  }
  // 3. 重置流式状态
  streaming.value = false
  loading.value = false
}

// Human-in-the-loop 恢复（确认/拒绝）
async function handleResume(action: string, msg: ChatMessage) {
  if (!currentConversationId.value || resuming.value) return
  resuming.value = true

  // ─── 就地覆盖模式 ───
  // 不新建 assistant 消息，直接在当前这条 interrupt 气泡上更新：
  //   - 隐藏审批按钮
  //   - 撕掉"草稿预览"徽章
  //   - 清空旧 draft 内容，让 resume 流式 content += 时从空串开始拼
  // 这样"同一个气泡状态流转"，切会话回来也能和后端 ai_message 表一一对应
  msg.interrupted = false
  msg.isDraft = false
  msg.content = ''

  const aiMsgIndex = messages.value.indexOf(msg)
  if (aiMsgIndex < 0) {
    console.error('handleResume: 找不到 msg 在 messages 里的位置')
    resuming.value = false
    return
  }

  loading.value = true
  streaming.value = true
  scrollToBottom(true)

  try {
    await streamResume(action, aiMsgIndex)
  } catch (error: any) {
    if (error.name === 'AbortError') return
    console.error('恢复失败:', error)
    messages.value[aiMsgIndex].content = '恢复执行失败，请重试。'
    ElMessage.error(error.message || '恢复失败')
  } finally {
    loading.value = false
    streaming.value = false
    resuming.value = false
    currentAbortController = null
    scrollToBottom()
  }
}

// 跳转到草稿编辑页
function editDraft(articleId: string) {
  router.push(`/edit-article?id=${articleId}`)
}

// SSE 流式 resume
async function streamResume(action: string, aiMsgIndex: number) {
  const token = localStorage.getItem('token')
  currentAbortController = new AbortController()

  const response = await fetch('/api/agent/chat/resume/stream', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify({
      conversationId: currentConversationId.value,
      action
    }),
    signal: currentAbortController.signal
  })

  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() || ''

    for (const event of events) {
      if (!event.trim()) continue

      const dataLines: string[] = []
      for (const line of event.split('\n')) {
        if (line.startsWith('data:')) {
          dataLines.push(line.substring(5))
        }
      }
      if (dataLines.length === 0) continue

      const data = dataLines.join('\n')
      if (!data) continue

      if (data.startsWith('__CONV_ID__:')) continue

      if (data.startsWith('__PROGRESS__:')) {
        const progressData = data.substring(13).trim()
        handleProgress(aiMsgIndex, progressData)
        scrollToBottom()
        continue
      }

      if (data.startsWith('__INTERRUPTED__:')) {
        try {
          const payload = JSON.parse(data.substring(16).trim())
          const msg = messages.value[aiMsgIndex]
          if (payload.draft) {
            msg.content = payload.draft
            msg.isDraft = true
          }
          msg.interrupted = true
          msg.interruptPayload = payload
          if (msg.progressSteps) {
            for (const step of msg.progressSteps) step.status = 'done'
          }
        } catch (e) {
          console.error('解析中断数据失败:', e)
        }
        scrollToBottom()
        continue
      }

      // HITL 草稿已保存事件（resume approve 后后端下发）
      if (data.startsWith('__DRAFT_SAVED__:')) {
        try {
          const payload = JSON.parse(data.substring(16).trim())
          const msg = messages.value[aiMsgIndex]
          msg.draftArticleId = payload.draftArticleId
          msg.draftTitle = payload.title || ''
          msg.isDraft = false
        } catch (e) {
          console.error('解析 __DRAFT_SAVED__ 事件失败:', e)
        }
        continue
      }

      if (data.startsWith('[ERROR]')) {
        throw new Error(data.substring(7).trim())
      }

      if (data.trim() === '[DONE]') continue
      if (data.trim().startsWith('{') && data.includes('conversationId')) continue

      messages.value[aiMsgIndex].content += data.replace(/\\n/g, '\n')
      scrollToBottom()
    }
  }
}

// 换行
function newLine() {
  userInput.value += '\n'
}

// 滚动到底部
// force=true 时无视 autoScrollToBottom，强制贴底并恢复自动跟随（用于用户主动发送消息、切会话、恢复中断等场景）
function scrollToBottom(force = false) {
  if (force) {
    autoScrollToBottom.value = true
  }
  if (!autoScrollToBottom.value) return
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

// 监听消息列表滚动：用户往上滑超过阈值则暂停自动跟随，回到底部附近则恢复
function handleMessageScroll() {
  const el = messageListRef.value
  if (!el) return
  const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  autoScrollToBottom.value = distanceToBottom < SCROLL_BOTTOM_THRESHOLD
}

// Markdown渲染
// 流式过程中 content 持续变化，不做缓存；流结束后的历史消息可缓存
const renderedCache = new Map<string, string>()

// 预处理markdown，修复AI输出的常见格式问题
function preprocessMarkdown(content: string): string {
  return content
    // 修复标题格式：##标题 → ## 标题（1-6级标题）
    .replace(/^(#{1,6})([^#\s])/gm, '$1 $2')
    // 行首 -非空格字符 补空格，使其成为合法的markdown列表项
    .replace(/^-(\S)/gm, '- $1')
    // 将 **文字：** 或 **文字** 直接转为 <strong> 标签，避免 marked 配对错误
    .replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
}

/**
 * 保护不完整的表格：流式传输中表格可能被截断，
 * marked 解析不完整表格会渲染成乱码。
 * 检测最后一个未闭合的表格块，将其替换为预格式化文本暂存。
 */
function protectIncompleteTable(content: string): string {
  const lines = content.split('\n')
  
  // 从末尾向前找，检测是否处于一个未结束的表格中
  let tableStartIndex = -1
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim()
    // 表格行特征：以 | 开头或包含 | 分隔
    if (line.startsWith('|') || /^\|.*\|$/.test(line)) {
      tableStartIndex = i
    } else if (tableStartIndex !== -1) {
      // 遇到非表格行，说明表格从 tableStartIndex 开始
      break
    }
  }
  
  // 没有检测到表格行，直接返回
  if (tableStartIndex === -1) return content
  
  // 检查这个表格是否完整（表格后面有非表格内容或空行说明已结束）
  const lastLine = lines[lines.length - 1].trim()
  const isTableEnded = lastLine === '' || (!lastLine.startsWith('|') && !/\|/.test(lastLine))
  
  if (isTableEnded) return content
  
  // 表格未结束，检查是否至少有表头+分隔行（最少2行才算有效表格开始）
  let tableLines = lines.slice(tableStartIndex)
  if (tableLines.length < 2) {
    // 只有一行，可能还没形成表格，用 <pre> 暂存
    const before = lines.slice(0, tableStartIndex).join('\n')
    const tablePart = tableLines.join('\n')
    return before + (before ? '\n' : '') + '\n```\n' + tablePart + '\n```'
  }
  
  // 有分隔行（第二行全是 |、-、:、空格），说明表格结构已开始
  const separatorLine = tableLines[1].trim()
  const isSeparator = /^\|?[\s\-:|]+\|?$/.test(separatorLine)
  
  if (!isSeparator) {
    // 没有分隔行，不是有效表格，直接返回
    return content
  }
  
  // 有效但未结束的表格，用 <pre> 暂存整个表格块
  const before = lines.slice(0, tableStartIndex).join('\n')
  const tablePart = tableLines.join('\n')
  return before + (before ? '\n' : '') + '\n<pre class="streaming-table">' + tablePart.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>'
}

function renderMarkdown(content: string): string {
  if (!content) return ''
  
  // 流式进行中不使用缓存（content 持续变化）
  if (!streaming.value) {
    const cached = renderedCache.get(content)
    if (cached) return cached
  }
  
  let processed = preprocessMarkdown(content)
  
  // 流式进行中，保护不完整的表格
  if (streaming.value) {
    processed = protectIncompleteTable(processed)
  }
  
  const rendered = marked(processed) as string
  
  // 非流式状态下缓存结果（历史消息）
  if (!streaming.value) {
    renderedCache.set(content, rendered)
    // 限制缓存大小
    if (renderedCache.size > 100) {
      const firstKey = renderedCache.keys().next().value
      if (firstKey) renderedCache.delete(firstKey)
    }
  }
  
  return rendered
}

// 新窗口打开文章详情
function openArticle(articleId: string) {
  window.open(`/article/${articleId}`, '_blank')
}

// 格式化时间
function formatTime(timeStr: string): string {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  if (diff < 604800000) return Math.floor(diff / 86400000) + '天前'
  
  return `${date.getMonth() + 1}/${date.getDate()}`
}

// 获取头像URL
function getAvatarUrl(url: string | undefined): string {
  if (!url) {
    return 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
  }
  if (url.startsWith('http://') || url.startsWith('https://')) {
    if (url.includes('localhost:8080')) {
      return url.replace(/https?:\/\/localhost:8080/, '')
    }
    return url
  }
  if (url.startsWith('/uploads')) return url
  return url
}

function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
}

// 文章卡片封面加载失败：缩略图回退原图，原图回退默认封面
function handleArticleCoverError(e: Event, originalCover?: string) {
  const target = e.target as HTMLImageElement
  const currentSrc = target.src
  
  if (currentSrc.includes('/thumbnails/') && originalCover) {
    target.src = originalCover
    return
  }
  
  target.src = '/images/default-cover.jpg'
}

// 窗口大小变化
function handleResize() {
  if (window.innerWidth > 768) {
    showSidebar.value = true
  }
}

// 登录弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const dialogWidth = ref(window.innerWidth <= 480 ? '92%' : '420px')

// 登录过期处理：跳转首页并弹出登录弹窗
function handleAuthExpired() {
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
  
  loadConversations()
  
  // 如果有保存的会话ID，加载该会话的消息
  if (currentConversationId.value) {
    loadingMessages.value = true
    try {
      const res = await request.get(`/agent/conversations/${currentConversationId.value}/messages`)
      if (res.code === 200 && res.data) {
        messages.value = res.data.map((msg: any) => ({
          role: msg.role,
          content: msg.content,
          image: msg.imagePaths && msg.imagePaths.length > 0 ? `/uploads/${msg.imagePaths[0]}` : null,
          articles: msg.articleCards || []
        }))
      }
    } catch (error) {
      console.error('加载会话消息失败:', error)
      currentConversationId.value = null
      localStorage.removeItem('ai_conversation_id')
    } finally {
      loadingMessages.value = false
    }
  }
  
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.ai-chat-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  background: #f5f7fa;
}

/* 导航栏 */
.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 70px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
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
  color: #409eff;
  cursor: pointer;
  transition: all 0.3s;
}

.logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.logo-text {
  display: inline;
}

.logo:hover {
  transform: scale(1.05);
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #333;
}

.nav-btn {
  background: transparent;
  color: #666;
  border: 1px solid #ddd;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.nav-btn:hover {
  border-color: #409eff;
  color: #409eff;
}

/* 主容器 */
.chat-container {
  padding-top: 70px;
  height: 100vh;
  display: flex;
}

/* 左侧会话列表 */
.conversation-sidebar {
  width: 280px;
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sidebar-header h3 {
  margin: 0;
  font-size: 16px;
  color: #333;
  font-weight: 600;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: #409eff;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.2s ease, transform 0.15s ease;
}

.new-chat-btn:hover {
  background: #66b1ff;
  transform: translateY(-1px);
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  margin-bottom: 6px;
  transition: all 0.2s;
}

.conversation-item:hover {
  background: #f3f4f6;
}

.conversation-item.active {
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
}

.conv-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #f0f7ff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.conv-icon svg {
  color: #409eff;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 14px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

.conv-time {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.delete-btn {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  padding: 6px;
  color: #909399;
  border-radius: 6px;
}

.conversation-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: #f56c6c;
  background: #fef0f0;
}

.no-conversations,
.loading-conversations {
  text-align: center;
  color: #909399;
  padding: 40px 0;
  font-size: 14px;
}

/* 右侧聊天区域 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

.mobile-back-btn {
  display: none;
  position: absolute;
  top: 15px;
  left: 15px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  z-index: 10;
}

/* 欢迎区域 —— 极简冷静风，左对齐排版 */
.welcome-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.welcome-inner {
  width: 100%;
  max-width: 640px;
  text-align: left;
}

.welcome-eyebrow {
  font-size: 12px;
  letter-spacing: 0.12em;
  color: #94a3b8;
  text-transform: uppercase;
  margin-bottom: 16px;
  font-weight: 500;
}

.welcome-title {
  font-size: 30px;
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.02em;
  line-height: 1.2;
  margin-bottom: 10px;
}

.welcome-desc {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 36px;
}

/* 快捷问题 —— 列表风，低饱和 */
.quick-questions {
  display: flex;
  flex-direction: column;
  border-top: 1px solid #edf0f3;
}

.quick-question-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 4px;
  border-bottom: 1px solid #edf0f3;
  cursor: pointer;
  transition: padding 0.2s ease, color 0.2s ease;
  color: #374151;
}

.quick-question-item:hover {
  padding-left: 10px;
  color: #111827;
}

.quick-question-item .qq-text {
  font-size: 14px;
  line-height: 1.5;
}

.quick-question-item .qq-arrow {
  color: #cbd5e1;
  flex-shrink: 0;
  transition: transform 0.2s ease, color 0.2s ease;
}

.quick-question-item:hover .qq-arrow {
  color: #111827;
  transform: translate(2px, -2px);
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 30px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.message-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f7ff;
  overflow: hidden;
}

.message-avatar svg {
  width: 24px;
  height: 24px;
  color: #409eff;
}

.message-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.message-content {
  max-width: 70%;
}

/* 用户消息内容靠右 */
.message-item.user .message-content {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

/* 用户发送的图片 */
.message-image {
  max-width: 300px;
  max-height: 200px;
  border-radius: 8px;
  margin-bottom: 8px;
  object-fit: contain;
  display: block;
}

.message-item.user .message-image {
  margin-left: auto;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.message-item.user .message-bubble {
  background: #409eff;
  color: white;
  display: inline-block;
  border-radius: 14px 4px 14px 14px;
}

.message-item.assistant .message-bubble {
  background: white;
  color: #1f2937;
  border: 1px solid #edf0f3;
  border-radius: 4px 14px 14px 14px;
  padding: 14px 18px;
  line-height: 1.75;
}

/* 文章卡片容器 */
.article-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  background: linear-gradient(180deg, #f8fafc 0%, #f3f5f9 100%);
  border-radius: 12px;
  border: 1px solid #eef1f6;
}

/* 单个卡片 */
.article-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: white;
  border-radius: 10px;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  border: 1px solid #edf0f3;
  align-items: stretch;
}

.article-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.12);
  border-color: #c7e0ff;
}

/* 封面图 */
.card-cover {
  width: 110px;
  height: 74px;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
  background: linear-gradient(135deg, #eef4ff 0%, #e3ecff 100%);
}

.card-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* 卡片信息 */
.card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 4px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.card-summary {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.card-meta .author {
  color: #409eff;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 45%;
}

.card-meta .stats {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.card-meta .stats .stat-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.card-meta .stats .stat-item svg {
  opacity: 0.6;
}

/* Markdown样式 */
.message-bubble :deep(pre) {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
}

.message-item.user .message-bubble :deep(pre) {
  background: rgba(255, 255, 255, 0.15);
}

.message-bubble :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
}

.message-item.user .message-bubble :deep(code) {
  background: rgba(255, 255, 255, 0.15);
}

.message-bubble :deep(pre code) {
  background: transparent;
  padding: 0;
}

.message-bubble :deep(strong) {
  font-weight: 600;
  color: #1a1a1a;
}

.message-bubble :deep(p) {
  margin: 0 0 10px 0;
}

.message-bubble :deep(p:last-child) {
  margin-bottom: 0;
}

.message-bubble :deep(ul),
.message-bubble :deep(ol) {
  padding-left: 20px;
  margin: 10px 0;
}

.message-bubble :deep(li) {
  margin-bottom: 6px;
  line-height: 1.7;
}

.message-bubble :deep(blockquote) {
  border-left: 3px solid #409eff;
  padding-left: 12px;
  margin: 8px 0;
  color: #666;
}

.message-bubble :deep(a) {
  color: #409eff;
  text-decoration: none;
}

.message-bubble :deep(a:hover) {
  text-decoration: underline;
}

.message-bubble :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}

.message-bubble :deep(th),
.message-bubble :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 6px 12px;
  text-align: left;
}

.message-bubble :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

/* 流式传输中未完成的表格，用等宽字体暂存显示 */
.message-bubble :deep(.streaming-table) {
  background: #f5f7fa;
  padding: 8px 12px;
  border-radius: 6px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  white-space: pre;
  overflow-x: auto;
  margin: 8px 0;
  line-height: 1.6;
  color: #555;
}

/* 加载动画 */
.typing-indicator {
  display: flex;
  gap: 5px;
  padding: 8px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #409eff;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) {
  animation-delay: 0s;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.6;
  }
  30% {
    transform: translateY(-8px);
    opacity: 1;
  }
}

/* 执行进度步骤条 */
.progress-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 18px;
  background: linear-gradient(180deg, #fafbfd 0%, #f5f7fa 100%);
  border: 1px solid #edf0f3;
  border-radius: 12px;
  margin-bottom: 4px;
  min-width: 220px;
}

.progress-step {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #909399;
  transition: color 0.3s, opacity 0.3s;
}

.progress-step.active {
  color: #303133;
}

.progress-step.done {
  color: #67c23a;
}

.progress-step.pending {
  opacity: 0.5;
}

.step-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.step-indicator svg {
  color: #67c23a;
}

.step-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c0c4cc;
}

.step-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #e4e7ed;
  border-top-color: #409eff;
  border-radius: 50%;
  animation: stepSpin 0.8s linear infinite;
}

@keyframes stepSpin {
  to { transform: rotate(360deg); }
}

.step-label {
  font-weight: 500;
}

.step-detail {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

/* 流式生成中指示器 */
.generating-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0 2px;
  color: #909399;
  font-size: 12px;
}

.generating-dot-pulse {
  position: relative;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  animation: dotPulse 1.5s infinite linear;
}

.generating-dot-pulse::before,
.generating-dot-pulse::after {
  content: '';
  display: inline-block;
  position: absolute;
  top: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
}

.generating-dot-pulse::before {
  left: -12px;
  animation: dotPulse 1.5s infinite linear;
  animation-delay: -0.4s;
}

.generating-dot-pulse::after {
  left: 12px;
  animation: dotPulse 1.5s infinite linear;
  animation-delay: 0.4s;
}

@keyframes dotPulse {
  0%, 60%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  30% {
    opacity: 1;
    transform: scale(1);
  }
}

/* Human-in-the-loop 审批区域 */
.interrupt-actions {
  margin-top: 12px;
  padding: 14px 16px;
  background: linear-gradient(135deg, #f3f8ff 0%, #ecf5ff 100%);
  border: 1px solid #d9ecff;
  border-radius: 10px;
}

.interrupt-hint {
  font-size: 13px;
  color: #4a5c72;
  margin-bottom: 10px;
  line-height: 1.5;
}

.interrupt-buttons {
  display: flex;
  gap: 10px;
}

.interrupt-btn {
  padding: 7px 22px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.interrupt-btn.approve {
  background: #409eff;
  color: white;
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}

.interrupt-btn.approve:hover:not(:disabled) {
  background: #66b1ff;
  border-color: #66b1ff;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

.interrupt-btn.reject {
  background: white;
  color: #606266;
  border-color: #dcdfe6;
}

.interrupt-btn.reject:hover:not(:disabled) {
  background: #f5f7fa;
  color: #909399;
  border-color: #c0c4cc;
}

.interrupt-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 草稿预览样式 —— 克制的中性灰 */
.draft-bubble {
  border: 1px solid #e5e7eb !important;
  background: #fafbfc !important;
  position: relative;
}

.draft-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: #1f2937;
  color: white;
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  margin-bottom: 10px;
  letter-spacing: 0.02em;
}

.draft-badge svg {
  flex-shrink: 0;
}

.interrupt-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 暂停按钮 */
.input-wrapper .stop-btn {
  width: 38px;
  height: 38px;
  background: #1f2937;
  border: none;
  border-radius: 10px;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, transform 0.15s ease;
  flex-shrink: 0;
}

.input-wrapper .stop-btn:hover {
  background: #374151;
  transform: translateY(-1px);
}

.input-wrapper .stop-btn svg {
  width: 16px;
  height: 16px;
}

/* 输入区域 */
.input-area {
  border-top: 1px solid #e5e7eb;
  padding: 16px 30px;
  background: white;
}

/* 图片预览（多图） */
.image-preview-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.image-preview-item {
  position: relative;
  display: inline-block;
}

.image-preview-item img {
  max-width: 100px;
  max-height: 70px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  object-fit: cover;
}

.remove-image-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 22px;
  height: 22px;
  background: #f56c6c;
  color: white;
  border: 2px solid white;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: background 0.2s;
}

.remove-image-btn:hover {
  background: #e04040;
}

/* 上传进度条样式 */
.image-preview-item.uploading {
  position: relative;
}

.image-preview-item.uploading img {
  opacity: 0.6;
}

.upload-progress-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  overflow: hidden;
}

.upload-progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 4px;
  background: #409eff;
  border-radius: 0 0 8px 8px;
  transition: width 0.2s ease;
}

.upload-progress-text {
  font-size: 12px;
  font-weight: 600;
  color: #409eff;
  z-index: 1;
}

.input-wrapper {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #ffffff;
  border: 1px solid #e6e9ef;
  border-radius: 14px;
  padding: 10px 12px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #111827;
  box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.06);
}

/* 已移除：模式切换按钮（统一走完整流程） */

.upload-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #9ca3af;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: color 0.2s ease, background 0.2s ease;
}

.upload-btn:hover:not(:disabled) {
  color: #1f2937;
  background: #f3f4f6;
}

.upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-wrapper textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: #333;
  resize: none;
  height: 24px;
  max-height: 120px;
  font-family: inherit;
  line-height: 24px;
  padding: 0;
  margin: 0;
}

.input-wrapper textarea::placeholder {
  color: #999;
}

.input-wrapper textarea:disabled {
  cursor: not-allowed;
}

.input-wrapper .send-btn {
  width: 38px;
  height: 38px;
  background: #409eff;
  border: none;
  border-radius: 10px;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, transform 0.15s ease;
  flex-shrink: 0;
}

.input-wrapper .send-btn:hover:not(:disabled) {
  background: #66b1ff;
  transform: translateY(-1px);
}

.input-wrapper .send-btn:disabled {
  background: #cbd5e1;
  opacity: 1;
  cursor: not-allowed;
}

.input-wrapper .send-btn svg {
  width: 18px;
  height: 18px;
}

.input-tips {
  text-align: center;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 10px;
  letter-spacing: 0.01em;
}

.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 移动端适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 56px;
  }
  
  .logo {
    font-size: 18px;
    gap: 6px;
  }
  
  .logo-icon {
    width: 26px;
    height: 26px;
  }
  
  .page-title {
    font-size: 15px;
  }
  
  .nav-btn {
    padding: 8px 14px;
    font-size: 13px;
  }
  
  .chat-container {
    padding-top: 56px;
  }
  
  .conversation-sidebar {
    position: fixed;
    left: 0;
    top: 56px;
    bottom: 0;
    width: 280px;
    z-index: 100;
    transform: translateX(0);
    transition: transform 0.3s ease;
  }
  
  .conversation-sidebar.hidden {
    transform: translateX(-100%);
  }
  
  .mobile-back-btn {
    display: flex;
  }
  
  .sidebar-header {
    padding: 12px 15px;
  }
  
  .sidebar-header h3 {
    font-size: 15px;
  }
  
  .new-chat-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  .conversation-item {
    padding: 10px 15px;
  }
  
  /* 移动端删除按钮始终显示 */
  .delete-btn {
    opacity: 1;
  }
  
  .conv-title {
    font-size: 13px;
  }
  
  .conv-time {
    font-size: 11px;
  }
  
  .welcome-area {
    padding: 30px 20px;
  }
  
  .welcome-title {
    font-size: 22px;
  }
  
  .welcome-desc {
    font-size: 13px;
    margin-bottom: 24px;
  }
  
  .quick-question-item {
    padding: 12px 4px;
  }
  
  .quick-question-item svg {
    width: 18px;
    height: 18px;
  }
  
  .quick-question-item span {
    font-size: 13px;
  }
  
  .message-list {
    padding: 15px;
    gap: 16px;
  }
  
  .message-item {
    gap: 10px;
  }
  
  .message-avatar {
    width: 32px;
    height: 32px;
  }
  
  .message-avatar svg {
    width: 20px;
    height: 20px;
  }
  
  .message-content {
    max-width: 82%;
  }
  
  .message-bubble {
    padding: 10px 14px;
    font-size: 14px;
    line-height: 1.5;
  }
  
  .message-bubble :deep(pre) {
    padding: 10px;
    font-size: 12px;
  }
  
  .message-bubble :deep(code) {
    font-size: 12px;
  }
  
  .input-area {
    padding: 12px 15px;
  }
  
  .input-wrapper {
    padding: 8px 10px;
    border-radius: 10px;
  }
  
  .input-wrapper textarea {
    font-size: 14px;
  }
  
  .input-wrapper .send-btn {
    width: 36px;
    height: 36px;
    border-radius: 8px;
  }
  
  .input-wrapper .send-btn svg {
    width: 18px;
    height: 18px;
  }
  
  .upload-btn svg {
    width: 20px;
    height: 20px;
  }
  
  .input-tips {
    font-size: 11px;
    margin-top: 6px;
  }
  
  .message-image {
    max-width: 200px;
    max-height: 150px;
  }
  
  /* 移动端图片预览 */
  .image-preview-list {
    gap: 8px;
  }
  
  .image-preview-item img {
    max-width: 80px;
    max-height: 60px;
  }
  
  .remove-image-btn {
    width: 20px;
    height: 20px;
    top: -6px;
    right: -6px;
  }
  
  /* 移动端文章卡片 */
  .article-cards {
    grid-template-columns: 1fr;
    gap: 8px;
    padding: 10px;
    margin-top: 10px;
  }
  
  .article-card {
    padding: 10px;
  }
  
  .card-cover {
    width: 80px;
    height: 55px;
  }
  
  .card-title {
    font-size: 13px;
  }
  
  .card-meta {
    font-size: 11px;
    margin-top: 3px;
  }
  
  .card-meta .stats {
    gap: 6px;
  }
  
  .card-meta .stats .stat-item svg {
    width: 12px;
    height: 12px;
  }
  
  .card-summary {
    font-size: 11px;
    margin-top: 3px;
  }
}

@media (max-width: 480px) {
  .navbar {
    padding: 0 12px;
    height: 52px;
  }
  
  .logo {
    font-size: 16px;
    gap: 5px;
  }
  
  .logo-icon {
    width: 24px;
    height: 24px;
  }
  
  .logo-text {
    display: none;
  }
  
  .page-title {
    font-size: 14px;
    flex: 1;
    text-align: center;
  }
  
  .nav-btn {
    padding: 6px 10px;
    font-size: 12px;
  }
  
  .chat-container {
    padding-top: 52px;
  }
  
  .conversation-sidebar {
    top: 52px;
    width: 100%;
  }
  
  .sidebar-header {
    padding: 10px 12px;
  }
  
  .conversation-item {
    padding: 10px 12px;
  }
  
  .welcome-area {
    padding: 25px 15px;
  }
  
  .welcome-title {
    font-size: 18px;
    margin-bottom: 6px;
  }
  
  .welcome-desc {
    font-size: 12px;
    margin-bottom: 22px;
  }
  
  .quick-question-item {
    padding: 10px 12px;
    gap: 8px;
    border-radius: 10px;
  }
  
  .quick-question-item svg {
    width: 16px;
    height: 16px;
  }
  
  .quick-question-item span {
    font-size: 12px;
  }
  
  .message-list {
    padding: 12px 10px;
    gap: 14px;
  }
  
  .message-item {
    gap: 8px;
  }
  
  .message-avatar {
    width: 28px;
    height: 28px;
  }
  
  .message-avatar svg {
    width: 18px;
    height: 18px;
  }
  
  .message-content {
    max-width: 85%;
  }
  
  .message-bubble {
    padding: 8px 12px;
    font-size: 13px;
    border-radius: 10px;
  }
  
  .message-item.user .message-bubble {
    border-radius: 10px 3px 10px 10px;
  }
  
  .message-item.assistant .message-bubble {
    border-radius: 3px 10px 10px 10px;
  }
  
  .message-bubble :deep(pre) {
    padding: 8px;
    font-size: 11px;
    border-radius: 6px;
  }
  
  .message-bubble :deep(code) {
    font-size: 11px;
    padding: 1px 4px;
  }
  
  .message-bubble :deep(ul),
  .message-bubble :deep(ol) {
    padding-left: 16px;
  }
  
  .input-area {
    padding: 10px 12px;
  }
  
  .input-wrapper {
    padding: 6px 8px;
    gap: 8px;
  }
  
  .input-wrapper textarea {
    font-size: 13px;
    height: 22px;
    line-height: 22px;
  }
  
  .input-wrapper textarea::placeholder {
    font-size: 12px;
  }
  
  .input-wrapper .send-btn {
    width: 34px;
    height: 34px;
  }
  
  .input-wrapper .send-btn svg {
    width: 16px;
    height: 16px;
  }
  
  .upload-btn {
    padding: 2px;
  }
  
  .upload-btn svg {
    width: 18px;
    height: 18px;
  }
  
  .input-tips {
    font-size: 10px;
  }
  
  .message-image {
    max-width: 160px;
    max-height: 120px;
    border-radius: 6px;
  }
  
  /* 超小屏图片预览 */
  .image-preview-list {
    gap: 6px;
  }
  
  .image-preview-item img {
    max-width: 60px;
    max-height: 45px;
    border-radius: 6px;
  }
  
  .remove-image-btn {
    width: 18px;
    height: 18px;
    top: -5px;
    right: -5px;
  }
  
  .remove-image-btn svg {
    width: 12px;
    height: 12px;
  }
  
  /* 超小屏文章卡片 */
  .article-cards {
    padding: 8px;
    gap: 6px;
    border-radius: 8px;
  }
  
  .article-card {
    padding: 8px;
    gap: 8px;
    border-radius: 6px;
  }
  
  .card-cover {
    width: 65px;
    height: 45px;
    border-radius: 4px;
  }
  
  .card-title {
    font-size: 12px;
    -webkit-line-clamp: 1;
  }
  
  .card-meta {
    font-size: 10px;
    flex-wrap: wrap;
    gap: 4px;
  }
  
  .card-meta .author {
    max-width: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .card-meta .stats {
    gap: 4px;
  }
  
  .card-meta .stats .stat-item {
    gap: 1px;
  }
  
  .card-meta .stats .stat-item svg {
    width: 10px;
    height: 10px;
  }
  
  .card-summary {
    display: none;
  }
  
  /* 加载动画缩小 */
  .typing-indicator span {
    width: 6px;
    height: 6px;
  }
}

/* 横屏模式优化 */
@media (max-height: 500px) and (orientation: landscape) {
  .welcome-area {
    padding: 15px;
  }
  
  .welcome-title {
    font-size: 16px;
  }
  
  .welcome-desc {
    font-size: 12px;
    margin-bottom: 12px;
  }
  
  .quick-question-item {
    padding: 10px 4px;
  }
  .quick-question-item {
    padding: 8px 10px;
  }
  
  .message-list {
    padding: 10px;
  }
  
  .input-area {
    padding: 8px 10px;
  }
}

/* HITL 草稿链接按钮 */
.draft-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 14px;
  background: #fafbfc;
  border: 1px solid #edf0f3;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.draft-link:hover {
  background: #f0f4f8;
  border-color: #d0d7de;
}

.draft-link-icon {
  width: 16px;
  height: 16px;
  color: #909399;
  flex-shrink: 0;
}

.draft-link-text {
  font-size: 13px;
  color: #606266;
}

.draft-link-title {
  color: #303133;
  font-weight: 500;
}

.draft-link-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #409eff;
  font-weight: 500;
  margin-left: auto;
  padding-left: 8px;
  border-left: 1px solid #edf0f3;
}

.draft-link-action svg {
  color: #409eff;
}
</style>
