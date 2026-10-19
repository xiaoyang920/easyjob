<template>
  <div :class="['ai-chat-page', { 'embedded-chat': embedded }]">
    <header v-if="embedded" class="article-chat-header">
      <div class="article-chat-heading"><span class="article-chat-mark">✎</span><div><strong>文章问答</strong><span>自己的对话，随时继续</span></div></div>
      <div class="article-chat-controls">
        <button @click="createNewConversation" :disabled="uploadingImage" title="围绕当前文章开启新话题">新话题</button>
        <button class="article-chat-close" aria-label="收起文章问答" @click="emit('close')">×</button>
      </div>
    </header>
    <button v-if="embedded" class="article-reader-link" @click="emit('openChatroom')">
      读者聊天室 · {{ readerCount }} 人在线<span v-if="readerUnread" class="reader-unread-dot"></span><span class="reader-link-arrow">↗</span>
    </button>

    <!-- 主容器 -->
    <div class="chat-container">
      <!-- 左侧会话列表 -->
      <div v-if="!embedded" :class="['conversation-sidebar', { hidden: !showSidebar }]">
        <div class="sidebar-header">
          <div class="sidebar-heading"><h3>我的对话</h3><p>随时回到之前的话题</p></div>
          <button class="new-chat-btn" @click="createNewConversation" :disabled="uploadingImage">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
            </svg>
            开启新对话
          </button>
        </div>
        
        <div class="conversation-search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg>
          <input v-model="libraryKeyword" class="conversation-search" aria-label="搜索对话" maxlength="80" placeholder="搜索对话…" />
          <button v-if="libraryKeyword" class="conversation-search-clear" aria-label="清空对话搜索" @click="libraryKeyword = ''">×</button>
        </div>
        <div class="conversation-list" ref="conversationListRef" @scroll="handleConversationScroll">
          <section v-for="group in conversationGroups" :key="group.scope" class="conversation-group">
          <button class="conversation-group-toggle" @click="group.scope === 'article' ? articleGroupOpen = !articleGroupOpen : generalGroupOpen = !generalGroupOpen" :aria-expanded="group.open">
            <span>{{ group.title }}</span><svg :class="{ expanded: group.open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>
          </button>
          <template v-if="group.open">
          <AiConversationItem
            v-for="conv in group.items"
            :key="conv.conversationId"
            :conversation="conv"
            :active="String(currentConversationId) === String(conv.conversationId)"
            :time="formatTime(conv.updateTime)"
            :status="conversationStatus(conv.conversationId)"
            :busy="conversationBusy(conv.conversationId)"
            :updating="updatingConversationIds.has(String(conv.conversationId))"
            @select="switchConversation(conv)"
            @pin="editConversation(conv, { pinned: !Number(conv.isPinned) })"
            @rename="renameConversation(conv)"
            @delete="confirmDeleteConversation(conv)"
          />
          <div v-if="group.items.length === 0 && !loadingConversations" class="no-conversations">{{ libraryKeyword.trim() ? '没有找到匹配的对话' : group.scope === 'article' ? '在文章页提问后，对话会出现在这里' : '开启新对话，聊聊你的想法' }}</div>
          <button v-if="hasMoreByScope[group.scope] && group.items.length" class="conversation-load-more" :disabled="loadingMoreConversations" @click="loadMoreConversations(group.scope)">加载更多</button>
          </template>
          </section>
          
          <div v-if="loadingConversations" class="loading-conversations">
            加载中...
          </div>
          <div v-if="loadingMoreConversations" class="loading-conversations">
            加载更多...
          </div>
        </div>
        <RouterLink to="/ai-memory" class="sidebar-memory-link"><span class="sidebar-memory-icon" aria-hidden="true">✦</span><span><strong>长期记忆</strong><small>管理记住的偏好与信息</small></span><span aria-hidden="true">↗</span></RouterLink>
      </div>

      <!-- 右侧聊天区域 -->
      <div class="chat-main">
        <div v-if="currentOriginArticleId" class="article-context-strip">
          <span>来源文章</span><button @click="openArticle(currentOriginArticleId)" :title="currentOriginArticleTitle">{{ currentOriginArticleTitle || '当前文章' }}</button>
          <small v-if="!embedded">也可以检索其他文章、进行对比</small>
        </div>
        <div v-if="historyLoadFailed" class="history-error">对话暂时无法加载。<button @click="initializeConversation">重新加载</button></div>
        <!-- 移动端返回按钮 -->
        <button class="mobile-back-btn" aria-label="返回对话列表" @click="showSidebar = true" v-if="!embedded && !showSidebar">
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
            <div class="welcome-eyebrow"><span class="quiet-dot"></span> {{ embedded ? '围绕文章，接着聊' : 'EasyJob · 写作助手' }}</div>
            <h2 class="welcome-title">{{ embedded ? '哪里想再弄明白一点？' : '从一个想法开始。' }}</h2>
            <p class="welcome-desc">{{ embedded ? '解释文章里的内容，也可以找其他文章一起对比。' : '找资料、理思路，或一起完成下一篇文章。' }}</p>

            <!-- 快捷问题 -->
            <div class="quick-questions">
              <button
                v-for="(q, index) in quickQuestions"
                :key="index"
                class="quick-question-item"
                @click="sendQuickQuestion(q)"
              >
                <span class="qq-text">{{ q }}</span>
                <svg class="qq-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M7 17L17 7M17 7H9M17 7V15"/>
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-else class="message-list" ref="messageListRef" :data-message-count="messages.length" :data-virtualized="messages.length > 60" @scroll="handleMessageScroll" @wheel.passive="handleHistoryWheel">
          <button v-if="activeSession.historyWindow.hasOlder" class="load-earlier-btn" :disabled="activeSession.historyBusy" @click="showEarlierMessages">{{ activeSession.historyBusy ? '加载中…' : '加载更早的消息' }}</button>
          <button v-if="questionIndexFailed" class="load-earlier-btn" @click="loadQuestionIndex(activeSession)">提问导航加载失败，点击重试</button>
          <div ref="virtualSpacer" class="virtual-spacer" :style="{height:`${virtual.before.value}px`}" aria-hidden="true"></div>
          <div 
            v-for="{ msg, index } in visibleMessages"
            :key="msg.itemId || index"
            :ref="virtual.measure"
            :data-virtual-key="msg.itemId || msg.messageId || `live:${index}`"
            :class="['message-item', msg.role]"
            :data-msg-index="index"
            :data-question-id="msg.role === 'user' ? (msg.messageId || msg.itemId) : undefined"
          >
            <div class="message-avatar">
              <svg v-if="msg.role === 'assistant'" viewBox="0 0 24 24" fill="currentColor"><path d="m14 4 6 6-9 9-7 1 1-7 9-9Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="m12 6 6 6M5 19l4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              <img v-else :src="avatarUrl(userAvatar, userNickName)" alt="" @error="onAvatarError($event, userNickName)">
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
              <AgentActivity v-if="msg.agent" :state="msg.agent" />
              <button v-if="msg.recoverable" class="interrupt-btn" :disabled="loading || resuming"
                @click="recoverReadOnlyRun(msg)">继续未完成任务</button>
              <div v-if="msg.role === 'assistant' && !msg.content && !msg.agent" class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <article v-if="msg.isDraft" class="draft-review-card">
                <header class="draft-review-header">
                  <div><span class="draft-review-eyebrow">{{ msg.interruptPayload?.targetArticleId ? '修改已有草稿' : '草稿预览' }}</span><h3>{{ msg.editedDraft?.title || msg.interruptPayload?.title || '待确认草稿' }}</h3></div>
                  <span class="draft-review-status">{{ msg.interrupted ? '等待确认' : '预览' }}</span>
                </header>
                <AiDraftEditor v-if="msg.interrupted" v-model="msg.editedDraft" :initial="draftEditFrom(msg.interruptPayload || {},msg.content)" :disabled="resuming" :citations="msg.interruptPayload?.citations || msg.citations">
                  <template #default="{ content, format }"><div class="draft-review-body" v-html="renderDraftPreview(content,format,msg.interruptPayload?.citations || msg.citations)"></div></template>
                </AiDraftEditor>
                <div v-else class="draft-review-body" v-html="renderDraftPreview(msg.editedDraft?.content || msg.content,msg.editedDraft?.content_format || msg.interruptPayload?.contentFormat,msg.interruptPayload?.citations || msg.citations)"></div>
                <p v-if="msg.approvalNotice" class="interrupt-hint" role="status">{{ msg.approvalNotice }}</p>
                <button v-if="msg.draftBackup || !msg.interrupted && msg.editedDraft" class="interrupt-btn" @click="copyEditedDraft(msg)">复制保留的手动修改</button>
                <footer v-if="msg.interrupted" class="draft-review-footer">
                  <p>{{ msg.interruptPayload?.message || '确认后保存到草稿箱，你也可以先提出修改意见。' }}</p>
                  <div class="interrupt-buttons">
                    <button class="interrupt-btn approve" @click="handleResume('approve', msg)" :disabled="resuming">{{ msg.interruptPayload?.targetArticleId ? '保存到原草稿' : '保存草稿' }}</button>
                    <button class="interrupt-btn reject" @click="handleResume('reject', msg)" :disabled="resuming">放弃保存</button>
                  </div>
                  <div class="draft-revision">
                    <textarea v-model="msg.draftRevision" placeholder="需要调整？写下修改意见，修改后重新确认。" maxlength="2000" rows="2" :disabled="resuming"></textarea>
                    <button @click="handleResume(msg.draftRevision!.trim(), msg)" :disabled="resuming || !msg.draftRevision?.trim()">让 AI 调整</button>
                  </div>
                </footer>
              </article>
              <div v-else-if="msg.content" class="message-bubble"><CodeContent :html="renderMarkdown(msg.content, msg.provisional ? [] : msg.citations)" @expand="openCodeViewer" /></div>
              <button v-if="msg.role === 'assistant' && msg.content && !msg.provisional && !msg.isDraft && !msg.agent?.answerReceiving" type="button" class="copy-answer-btn" @click="copyAnswer(msg.content)">复制回答</button>
              <AnswerFeedback v-if="msg.role==='assistant' && msg.runId && msg.content && !msg.provisional && !msg.interrupted && !msg.isDraft && !msg.recoverable && (!msg.agent || msg.agent.status==='complete') && !loading && !resuming" :run-id="msg.runId" /><div v-if="msg.agent?.answerReceiving" class="generating-indicator"><div class="generating-dot-pulse"></div><span>{{ msg.provisional ? '正在生成，完成后确认正文…' : '正在接收回答…' }}</span></div>
              <div v-if="msg.interrupted && !msg.isDraft" class="interrupt-actions">
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
                  文章已保存
                  <span v-if="msg.draftTitle" class="draft-link-title">《{{ msg.draftTitle }}》</span>
                </span>
                <span class="draft-link-action">
                  打开文章
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M7 17L17 7M17 7H9M17 7V15"/>
                  </svg>
                </span>
              </div>
              <div v-if="!msg.isDraft && msg.citations?.length" class="citation-list">
                <button v-for="(citation, citationIndex) in msg.citations" :key="citation.id"
                        class="citation-link" :title="citation.excerpt"
                        @click="openCitation(citation)">
                  {{ citationIndex + 1 }}. {{ citation.title }}
                </button>
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
          <div class="virtual-spacer" :style="{height:`${virtual.after.value}px`}" aria-hidden="true"></div>
        </div>

        <div v-if="activeSession.historyWindow.hasNewer" class="history-window-actions">
          <button class="load-earlier-btn" :disabled="activeSession.historyBusy" @click="showNewerMessages">加载后续消息</button>
          <button class="load-earlier-btn" :disabled="activeSession.historyBusy" @click="returnToLatest">回到最新消息 ↓</button>
        </div>
        <!-- 提问快速定位：消息区左侧的刻度导航 -->
        <QuestionRail
          v-if="!embedded && messageListRef && messages.length"
          :key="activeSession.key"
          :questions="railQuestions"
          :resolve-question="resolveQuestion"
          :container="messageListRef"
        />

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
            <button class="upload-btn" aria-label="添加图片" title="添加图片" @click="triggerImageUpload" :disabled="loading || uploadingImage">
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
              :placeholder="embedded ? '针对这篇文章继续提问…' : '写下问题，或一个还没成形的想法…'"
              aria-label="消息内容"
              @keydown.enter.exact="handleEnterKey"
              rows="1"
              ref="inputRef"
              :disabled="loading || loadingMessages || historyLoadFailed"
            ></textarea>
            <button 
              v-if="streaming"
              class="stop-btn" 
              @click="handleCancel"
              title="停止当前对话的生成"
              aria-label="停止生成"
              :disabled="!currentConversationId || activeSession.cancelling"
            >
              <svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
            </button>
            <button 
              v-else
              class="send-btn" 
              aria-label="发送消息"
              @click="sendMessage" 
              :disabled="(!userInput.trim() && selectedImages.length === 0) || loading || loadingMessages || historyLoadFailed"
            >
              <svg v-if="!loading" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
              <span v-else class="loading-spinner"></span>
            </button>
          </div>
          <div class="input-tips">
            <span class="tip-text">Enter 发送 · Shift + Enter 换行</span>
            <span class="tip-note">重要信息请核实来源</span>
          </div>
          <button v-if="embedded" class="expand-assistant-link" @click="expandInAssistant" :disabled="!currentConversationId" title="在智能助手中继续同一个对话">在智能助手中展开 ↗</button>
        </div>
      </div>
    </div>
  </div>

  <!-- 登录弹窗 -->
  <CodeViewer v-model="codeViewerOpen" :code="previewCode.text" :language="previewCode.language" :initial-font-size="16" />
  <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
    <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
  </el-dialog>
  <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
    <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
  </el-dialog>
</template>

<script setup lang="ts">
import { createDeliveryTiming } from '@/utils/deliveryTiming'
import { useVirtualMessages } from '@/composables/useVirtualMessages'
import AiConversationItem from '@/components/AiConversationItem.vue'
import { historyPage, mergeHistory, questionPreviews } from '@/utils/historyPaging'
import { aiConversationStatus, setViewedAiConversation, trackAiRun, refreshAiRuns } from '@/utils/aiRuns'
import { createChatSession, bindConversationId, beginChatOperation, finishChatOperation, releaseChatSessions, type ChatSession } from '@/utils/chatSessions'
import { authenticatedFetch } from '@/utils/authSession'
import { approvalRecovery } from '@/utils/approvalRecovery'
import AiDraftEditor from '@/components/AiDraftEditor.vue'
import { draftEditFrom,draftEditError,type DraftEdit } from '@/utils/draftEdit'
import { ref, shallowRef, shallowReactive, reactive, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { goBackOr } from '@/utils/navigation'
import { ElMessage, ElMessageBox } from 'element-plus'
import AnswerFeedback from '@/components/AnswerFeedback.vue'
import CodeContent from '@/components/CodeContent.vue'
import CodeViewer from '@/components/CodeViewer.vue'
import { renderChatMarkdown } from '@/utils/chatMarkdown'
import { avatarUrl, onAvatarError } from '@/utils/avatar'
import { safeHtml } from '@/utils/safeHtml'
import { draftBodyHtml, formatCitationHtml, type SourceLink } from '../utils/citationLinks'
import LoginForm from '@/components/LoginForm.vue'
import RegisterForm from '@/components/RegisterForm.vue'
import AgentActivity from '@/components/AgentActivity.vue'
import QuestionRail from '@/components/QuestionRail.vue'
import { createAgentState, applyAgentEvent, applyAnswerChunk, readSse, setRunStatus, restoreAgentState } from '@/utils/agentStream'
import type { AgentStreamState } from '@/utils/agentStream'
import request from '@/utils/request'
import { savedArticlePath } from '@/utils/articleLifecycle'
import { getThumbUrl } from '@/utils/image'
import { eventBus, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'

const router = useRouter()
const route = useRoute()
const codeViewerOpen = ref(false), previewCode = ref({text:'',language:''})
function openCodeViewer(code: {text:string;language:string}) { previewCode.value = code; codeViewerOpen.value = true }
async function copyAnswer(content: string) {
  try { await navigator.clipboard.writeText(content); ElMessage.success('已复制回答') }
  catch { ElMessage.error('复制失败，请检查浏览器剪贴板权限后重试') }
}
const props = withDefaults(defineProps<{
  embedded?: boolean
  originArticleId?: string
  originArticleTitle?: string
  readerCount?: number
  readerUnread?: boolean
}>(), { embedded: false, originArticleId: '', originArticleTitle: '', readerCount: 0, readerUnread: false })
const emit = defineEmits<{ close: []; openChatroom: []; loginRequired: [] }>()

// 用户信息
const userAvatar = ref(localStorage.getItem('avatar') || '')
const userNickName = localStorage.getItem('nickName') || ''

// 会话状态
const conversations = ref<any[]>([])
// Selection belongs to the signed-in account. Embedded article chats never use the
// general page's selection, so opening an article cannot reuse an unrelated chat.
function selectionStorageKey() {
  const userId = localStorage.getItem('userId')
  return userId ? `ai_conversation_id:${userId}` : null
}
function persistSelection(id: string | null) {
  if (props.embedded) return
  const key = selectionStorageKey()
  if (!key) return
  if (id) localStorage.setItem(key, id)
  else localStorage.removeItem(key)
}
type Session = ChatSession<ChatMessage, SelectedImage>
const sessions = shallowReactive(new Map<string, Session>())
function newSession(id: string | null = null): Session {
  const session = reactive(createChatSession<ChatMessage, SelectedImage>(id || crypto.randomUUID(), id))
  sessions.set(session.key, session)
  return session
}
const activeSession = shallowRef<Session>(newSession())
function sessionField<K extends keyof Session>(key: K) {
  return computed({ get: () => activeSession.value[key], set: (value: Session[K]) => { activeSession.value[key] = value } })
}
const currentConversationId = sessionField('conversationId')
const selectedConversation = ref<any | null>(null)
const currentOriginArticleId = sessionField('originArticleId')
currentOriginArticleId.value = props.originArticleId || null
const currentOriginArticleTitle = sessionField('originArticleTitle')
currentOriginArticleTitle.value = props.originArticleTitle
const loadingConversations = ref(false)
const loadingMoreConversations = ref(false)  // 加载更多中
type ConversationScope = 'general' | 'article'
const hasMoreByScope = ref<Record<ConversationScope, boolean>>({ general: true, article: true })
const generalGroupOpen = ref(true)
const articleGroupOpen = ref(false)
function groupItems(scope: ConversationScope) {
  const items = conversations.value.filter(c => scope === 'article' ? !!c.originArticleId : !c.originArticleId)
  const selected = selectedConversation.value
  if (!libraryKeyword.value.trim() && selected && (scope === 'article' ? !!selected.originArticleId : !selected.originArticleId)
      && !items.some(c => String(c.conversationId) === String(selected.conversationId))) items.unshift(selected)
  // Preserve server ordering within each pin tier, including a selected chat
  // outside the loaded page; unpinned selection must never precede pinned rows.
  return items.sort((a, b) => Number(!!Number(b.isPinned)) - Number(!!Number(a.isPinned)))
}
const conversationGroups = computed(() => [
  { scope: 'general' as const, title: '普通聊天', open: generalGroupOpen.value, items: groupItems('general') },
  { scope: 'article' as const, title: '文章问答', open: articleGroupOpen.value, items: groupItems('article') }
])
const conversationListRef = ref<HTMLElement>()  // 会话列表容器
const showSidebar = ref(true)
const historyLoadFailed = sessionField('historyLoadFailed')
let historyLoadVersion = 0
let mounted = false

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

interface Citation {
  id: string
  articleId: string
  title: string
  chunkIndex: number
  excerpt: string
  url?: string
}

function openCitation(citation: Citation) {
  if (citation.articleId) openArticle(citation.articleId)
  else if (citation.url && /^https?:\/\//i.test(citation.url)) window.open(citation.url, '_blank', 'noopener,noreferrer')
}

interface ChatMessage {
  itemId?: string
  messageId?: string
  turnId?: string
  role: 'user' | 'assistant'
  content: string
  provisional?: boolean
  image?: string | null
  articles?: ArticleCard[]  // 文章卡片数据
  citations?: Citation[]
  agent?: AgentStreamState
  runId?: string
  recoverable?: boolean
  draftRevision?: string
  editedDraft?: DraftEdit
  draftBackup?: DraftEdit
  approvalNotice?: string
  interrupted?: boolean  // 是否被 interrupt 暂停
  interruptPayload?: Record<string, any>  // interrupt 携带的数据（如草稿内容）
  isDraft?: boolean  // 当前内容是否为草稿
  draftArticleId?: string  // HITL 草稿确认后关联的 article_info.article_id，用 string 避免 JS 精度丢失
  draftTitle?: string  // 草稿标题，显示在"编辑草稿"按钮旁边
}

const railQuestions = computed(() => questionPreviews(activeSession.value.questionIndex, messages.value))
const questionIndexFailed = sessionField('questionIndexFailed')

async function loadQuestionIndex(session: Session) {
  if (!session.conversationId) return
  const version = ++session.questionVersion
  let after: string | undefined, snapshot: string | undefined
  const items: Session['questionIndex'] = []
  try {
    do {
      const response = await request.get(`/agent/conversations/${session.conversationId}/questions`, { params: { limit: 200, after, snapshot } })
      if (!mounted || version !== session.questionVersion) return
      if (Array.isArray(response.data)) return // Older server compatibility.
      if (response.code !== 200 || !Array.isArray(response.data?.items)) throw new Error('提问导航加载失败')
      items.push(...response.data.items)
      if (!response.data.hasMore) break
      const next = response.data.nextCursor
      if (!next || next === after) throw new Error('提问导航游标无效')
      after = next; snapshot = response.data.snapshot
    } while (true)
    session.questionIndex = items
    session.questionIndexFailed = false
  } catch {
    if (mounted && version === session.questionVersion) session.questionIndexFailed = true
  }
}

// Keep the reactive objects used by the stream reader when replacing a window.
function retainLiveMessages(session: Session, incoming: ChatMessage[], latest: boolean) {
  if (!session.loading || !session.liveMessages.length) return incoming
  const user = session.liveMessages.find(m => m.role === 'user')
  const answer = session.liveMessages.find(m => m.role === 'assistant')
  const turnId = user?.messageId || answer?.turnId
  if (!latest && !incoming.some(m => turnId && m.turnId === turnId)) return incoming
  for (const live of session.liveMessages) {
    const index = incoming.findIndex(m => m.itemId === live.itemId ||
      (live.messageId && m.messageId === live.messageId) ||
      (live.role === 'assistant' && m.role === 'assistant' &&
        ((live.runId && (m.runId === live.runId || m.interruptPayload?.runId === live.runId)) || (turnId && m.turnId === turnId))))
    if (index >= 0) incoming[index] = live
    else incoming.push(live)
  }
  return incoming
}

async function loadHistoryWindow(session: Session, params: Record<string, string> = {}, mode: 'replace' | 'older' | 'newer' = 'replace') {
  if (!session.conversationId) return false
  const version = ++session.historyVersion
  session.historyBusy = true
  try {
    const response = await request.get(`/agent/conversations/${session.conversationId}/messages`, { params: { limit: 20, ...params } })
    if (!mounted || version !== session.historyVersion) return false
    if (response.code !== 200) throw new Error('加载历史消息失败')
    const page = historyPage(response.data)
    const incoming = page.items.map(toChatMessage)
    if (mode === 'replace') {
      session.messages = retainLiveMessages(session, incoming, !page.hasNewer)
      const { items: _, ...window } = page
      session.historyWindow = window
    } else {
      session.messages = mergeHistory(session.messages, incoming, mode === 'older')
      if (mode === 'older') Object.assign(session.historyWindow, { beforeCursor: page.beforeCursor, hasOlder: page.hasOlder })
      else Object.assign(session.historyWindow, { afterCursor: page.afterCursor, hasNewer: page.hasNewer })
    }
    session.historyLoaded = true
    return true
  } finally {
    if (version === session.historyVersion) session.historyBusy = false
  }
}

async function showEarlierMessages() {
  const session = activeSession.value, el = messageListRef.value
  if (session.historyBusy || !session.historyWindow.beforeCursor) return
  const height = el?.scrollHeight || 0, top = el?.scrollTop || 0
  const anchor = virtual.captureAnchor()
  autoScrollToBottom.value = false
  try {
    if (!await loadHistoryWindow(session, { before: session.historyWindow.beforeCursor }, 'older')) return
    await nextTick()
    if (activeSession.value === session && session.messages.length > 60) await virtual.restoreAnchor(anchor)
    if (el && activeSession.value === session && session.messages.length <= 60) el.scrollTop = top + el.scrollHeight - height
  } catch { ElMessage.warning('加载更早消息失败，可重新尝试') }
}

async function showNewerMessages() {
  const session = activeSession.value
  if (session.historyBusy || !session.historyWindow.afterCursor) return
  try { await loadHistoryWindow(session, { after: session.historyWindow.afterCursor }, 'newer') }
  catch { ElMessage.warning('加载后续消息失败，可重新尝试') }
}

async function returnToLatest() {
  const session = activeSession.value
  try {
    if (await loadHistoryWindow(session) && activeSession.value === session) {
      scrollToBottom(true)
      if (!session.loading) void reconnectActiveRun(session).catch(() => ElMessage.warning('暂时无法同步运行状态，请重新加载'))
    }
  } catch { ElMessage.warning('加载最新消息失败，可重新尝试') }
}

async function resolveQuestion(id: string) {
  const session = activeSession.value
  autoScrollToBottom.value = false
  const localIndex = session.messages.findIndex(m => (m.messageId || m.itemId) === id)
  if (localIndex >= 0) {
    await virtual.scrollToIndex(localIndex)
    // A newer click on an already loaded question cancels an older remote jump.
    if (session.historyBusy) { session.historyVersion++; session.historyBusy = false }
    return true
  }
  if (!/^\d+$/.test(id)) return false
  try {
    const loaded = await loadHistoryWindow(session, { around: id })
    await nextTick()
    if (loaded && activeSession.value === session) await virtual.scrollToIndex(session.messages.findIndex(m => (m.messageId || m.itemId) === id))
    return loaded && activeSession.value === session
  } catch { ElMessage.warning('无法定位该提问，请重新尝试'); return false }
}

function toChatMessage(msg: any): ChatMessage {
  return {
    role: msg.role, content: msg.content || '',
    itemId: msg.itemId || (msg.messageId ? `message:${msg.messageId}` : msg.runId ? `run:${msg.runId}` : crypto.randomUUID()),
    messageId: msg.messageId, turnId: msg.turnId,
    runId: msg.runId, recoverable: !!msg.recoverable, agent: restoreAgentState(msg),
    image: msg.imagePaths?.length ? `/uploads/${msg.imagePaths[0]}` : null,
    articles: msg.articleCards || [], citations: msg.citations || [],
    interrupted: msg.interrupted || false, interruptPayload: msg.interruptPayload,
    isDraft: msg.isDraft || false, draftArticleId: msg.draftArticleId || undefined,
    draftTitle: msg.draftTitle || '', draftRevision: ''
  }
}
const messages = sessionField('messages')
const userInput = sessionField('userInput')
const loading = computed(() => activeSession.value.loading || activeSession.value.cancelling)
const streaming = sessionField('streaming')
const resuming = sessionField('resuming')
const loadingMessages = ref(false)  // 切换会话时的加载状态

// 自动跟随滚动到底部（用户手动往上滚后暂停，回到底部附近恢复）
const messageListRef = ref<HTMLElement>()
const virtual = useVirtualMessages(() => messages.value, messageListRef, (m,i) => m.itemId || m.messageId || `live:${i}`, m => m.role === 'user' ? 110 : Math.min(1000,180 + m.content.length / 50 * 24))
const virtualSpacer = virtual.spacer
const visibleMessages = computed(() => virtual.items.value.map(({item,index}) => ({msg:item,index})))
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
const selectedImages = sessionField('selectedImages')  // 支持多图
const imageInput = ref<HTMLInputElement>()
const uploadingImage = ref(false)  // 图片上传中状态
const uploadProgress = ref(0)  // 上传进度 0-100
const uploadingPreview = ref('')  // 上传中图片的预览URL

// 快捷问题
const quickQuestions = computed(() => props.embedded ? [
  '帮我梳理这篇文章的核心思路',
  '解释一下文章里的关键概念',
  '找一篇相关文章，和本文对比一下'
] : [
  '整理几篇 Spring Boot 入门文章',
  '最近有哪些值得关注的技术文章',
  '帮我写一篇聊聊前端工程化的草稿',
  '用简明语言解释一下 RAG'
])

const libraryKeyword = ref('')
const updatingConversationIds = reactive(new Set<string>())
function conversationBusy(id: string) {
  const session = sessions.get(String(id))
  return !!(session?.loading || session?.resuming || session?.cancelling)
}
const libraryPages: Record<ConversationScope,number> = { general: 1, article: 1 }
let libraryGeneration = 0
let librarySearchTimer: ReturnType<typeof setTimeout> | undefined
watch(libraryKeyword, () => { libraryGeneration++;clearTimeout(librarySearchTimer);librarySearchTimer=setTimeout(()=>void loadConversations(),300) })
async function loadConversations() {
  if (props.embedded) return
  const generation=++libraryGeneration
  loadingConversations.value=true
  try {
    const scopes:ConversationScope[]=['general','article']
    const results=await Promise.all(scopes.map(scope=>request.get('/agent/library',{params:{scope,keyword:libraryKeyword.value,page:1,size:20}})))
    if(!mounted || generation!==libraryGeneration)return
    conversations.value=results.flatMap(r=>r.data?.rows || [])
    scopes.forEach((scope,i)=>{libraryPages[scope]=1;hasMoreByScope.value[scope]=results[i].data.total>20})
  }catch{if(generation===libraryGeneration)ElMessage.error('加载对话列表失败，请稍后重试')}
  finally{if(generation===libraryGeneration)loadingConversations.value=false}
}
async function loadMoreConversations(scope:ConversationScope) {
  if(loadingConversations.value || loadingMoreConversations.value || !hasMoreByScope.value[scope])return
  const generation=libraryGeneration,page=libraryPages[scope]+1
  loadingMoreConversations.value=true
  try{
    const r=await request.get('/agent/library',{params:{scope,keyword:libraryKeyword.value,page,size:20}})
    if(!mounted || generation!==libraryGeneration)return
    const ids=new Set(conversations.value.map(c=>c.conversationId))
    conversations.value.push(...r.data.rows.filter((c:any)=>!ids.has(c.conversationId)))
    libraryPages[scope]=page;hasMoreByScope.value[scope]=r.data.total>page*20
  }catch{if(generation===libraryGeneration)ElMessage.error('加载更多对话失败')}
  finally{loadingMoreConversations.value=false}
}
async function editConversation(conv:any,edit:Record<string,unknown>){
  const id=String(conv.conversationId)
  if(updatingConversationIds.has(id))return
  updatingConversationIds.add(id)
  try{
    const result=await request.patch(`/agent/conversations/${id}`,{...edit,version:conv.metadataVersion ?? 0})
    const updated={...conv,metadataVersion:result.data?.version ?? (conv.metadataVersion ?? 0)+1,
      ...(typeof edit.title==='string'?{title:edit.title}:{}),...(typeof edit.pinned==='boolean'?{isPinned:Number(edit.pinned)}:{})}
    Object.assign(conv,updated)
    if(String(selectedConversation.value?.conversationId)===id)selectedConversation.value=updated
    ElMessage.success(typeof edit.pinned==='boolean'
      ?edit.pinned?`已置顶，固定在${conv.originArticleId?'文章问答':'普通聊天'}顶部`:'已取消置顶，恢复按最近更新排序'
      :'对话标题已更新')
    await loadConversations()
  }catch(e){ElMessage.error(e instanceof Error?e.message:'修改失败');await loadConversations()}
  finally{updatingConversationIds.delete(id)}
}
async function renameConversation(conv:any){
  if(updatingConversationIds.has(String(conv.conversationId)))return
  try{const {value}=await ElMessageBox.prompt('输入对话标题（1至80字）','重命名对话',{inputValue:conv.title||'',inputValidator:v=>!!v?.trim() && v.trim().length<=80 || '请输入1至80个字',confirmButtonText:'保存',cancelButtonText:'取消'});await editConversation(conv,{title:value.trim()})}catch{}
}

// 会话列表滚动事件
function handleConversationScroll() {
  const el = conversationListRef.value
  if (!el) return
  
  // 距离底部小于50px时触发加载
  const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  if (isNearBottom) {
    const group = conversationGroups.value.find(group => group.open && hasMoreByScope.value[group.scope])
    if (group) loadMoreConversations(group.scope)
  }
}

// 创建新会话
function createNewConversation() {
  if (uploadingImage.value) return
  historyLoadVersion += 1
  loadingMessages.value = false
  activeSession.value = newSession()
  currentConversationId.value = null
  selectedConversation.value = null
  persistSelection(null)
  currentOriginArticleId.value = props.embedded ? props.originArticleId || null : null
  currentOriginArticleTitle.value = props.embedded ? props.originArticleTitle : ''
  messages.value = []
  userInput.value = ''
  selectedImages.value = []
  historyLoadFailed.value = false
  if (!props.embedded && (route.query.conversationId || route.query.originArticleId)) router.replace({ path: '/ai-chat' })
  if (window.innerWidth <= 768) {
    showSidebar.value = false
  }
}

// 切换会话
async function switchConversation(conv: any) {
  if (uploadingImage.value) { ElMessage.info('图片上传完成后即可切换对话'); return }
  const id = String(conv.conversationId)
  if (currentConversationId.value === id && activeSession.value.historyLoaded) {
    if (window.innerWidth <= 768) showSidebar.value = false
    return
  }
  const version = ++historyLoadVersion
  const session = sessions.get(id) || newSession(id)
  activeSession.value = session
  session.unread = false
  selectedConversation.value = conv
  session.originArticleId = conv.originArticleId ? String(conv.originArticleId) : null
  session.originArticleTitle = conv.originArticleTitle || (props.embedded ? props.originArticleTitle : '')
  if (session.originArticleId && !props.embedded) articleGroupOpen.value = true
  persistSelection(id)
  loadingMessages.value = false
  if (window.innerWidth <= 768) showSidebar.value = false
  // Live callbacks remain bound to this session; never replace its partial reply with history.
  if (session.loading || session.resuming || session.cancelling) { scrollToBottom(true); return }
  loadingMessages.value = true
  session.historyLoadFailed = false
  try {
    if (!await loadHistoryWindow(session)) return
    if (!mounted || version !== historyLoadVersion) return
    void loadQuestionIndex(session)
    // Loading history must not wait for the entire generation to finish.
    loadingMessages.value = false
    void reconnectActiveRun(session).catch(() => { session.historyLoadFailed = true })
  } catch {
    if (version === historyLoadVersion && mounted) session.historyLoadFailed = true
  } finally {
    if (version === historyLoadVersion && mounted) {
      loadingMessages.value = false
      scrollToBottom(true)
    }
  }
}

function conversationStatus(id: string): string {
  const session = sessions.get(String(id))
  if (session?.loading) return '正在生成'
  if (session?.messages.at(-1)?.interrupted) return '等待确认'
  if (session?.unread) return session.messages.at(-1)?.interrupted ? '等待确认' : '有新回复'
  return aiConversationStatus(String(id))
}
function finishSession(session: Session, operation: number) {
  if (!finishChatOperation(session, operation)) return
  if (mounted && activeSession.value !== session) session.unread = true
  if (mounted && activeSession.value === session) scrollToBottom()
  if (mounted) { void refreshAiRuns(); void loadQuestionIndex(session) }
  session.liveMessages = []
}

// 删除会话
async function confirmDeleteConversation(conv: any) {
  if(conversationBusy(conv.conversationId) || updatingConversationIds.has(String(conv.conversationId)))return
  try {
    await ElMessageBox.confirm(`确定删除「${conv.title || '新对话'}」？删除后将无法恢复这段聊天记录。`,'删除对话',{
      type:'warning',confirmButtonText:'删除对话',cancelButtonText:'保留对话',autofocus:false
    })
  } catch { return }
  await deleteConversation(String(conv.conversationId))
}
async function deleteConversation(conversationId: string) {
  const session = sessions.get(String(conversationId))
  if (session?.loading || session?.resuming || session?.cancelling) { ElMessage.info('请先停止该对话的生成，再删除'); return }
  if(updatingConversationIds.has(conversationId))return
  updatingConversationIds.add(conversationId)
  try {
    const res = await request.delete(`/agent/conversations/${conversationId}`)
    if (res.code === 200) {
      conversations.value = conversations.value.filter(c => String(c.conversationId) !== String(conversationId))
      if (session) for (const [key, value] of sessions) if (value === session) sessions.delete(key)
      if (currentConversationId.value === conversationId) {
        createNewConversation()
      }
      ElMessage.success('删除成功')
    }
  } catch (error) {
    console.error('删除会话失败:', error)
    ElMessage.error('删除失败')
  } finally { updatingConversationIds.delete(conversationId) }
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
  const session = activeSession.value
  const content = session.userInput.trim()
  if (!content && session.selectedImages.length === 0) return
  if (session.loading || session.cancelling || uploadingImage.value || loadingMessages.value || session.historyLoadFailed || session.historyBusy) return
  if (!localStorage.getItem('token')) { requestLogin(); return }
  
  if (session.historyWindow.hasNewer) {
    try { if (!await loadHistoryWindow(session) || activeSession.value !== session) return }
    catch { ElMessage.warning('加载最新消息失败，本次输入已保留'); return }
  }
  // 添加用户消息（含图片预览）
  const userMsg: ChatMessage = {
    role: 'user', itemId: crypto.randomUUID(),
    content: content,
    image: session.selectedImages.length > 0 ? session.selectedImages[0].preview : null  // 显示第一张预览
  }
  session.messages.push(userMsg)
  session.historyLoaded = true
  
  // 暂存图片路径列表，清空输入
  const submittedImages = [...session.selectedImages]
  const imagePaths = session.selectedImages.map(img => img.path)
  session.userInput = ''
  session.selectedImages = []
  const operation = beginChatOperation(session)
  if (activeSession.value === session) scrollToBottom(true)
  
  // 准备AI回复占位
  const aiMessage: ChatMessage = {
    role: 'assistant', itemId: crypto.randomUUID(),
    content: '',
    agent: createAgentState()
  }
  session.messages.push(aiMessage)
  // Capture Vue's reactive objects; prepending history must not change the stream target.
  const msg = session.messages.at(-1)!
  session.liveMessages = session.messages.slice(-2)
  
  const timing = createDeliveryTiming(document)
  const stopTimingSelection = watch(activeSession, selected => { if (selected !== session) timing.invalidate() }, { flush:'sync' })
  try {
    session.streaming = true
    await streamChat(content, imagePaths, msg, session, timing)
  } catch (error: any) {
    // 用户主动取消不算错误
    if (error.name === 'AbortError' || !mounted) return
    if (error.status === 409 && session.conversationId) {
      // Rejected requests were never added to backend history. Keep their input editable.
      session.messages = session.messages.filter(item => !session.liveMessages.includes(item))
      session.liveMessages = []
      session.userInput = content
      session.selectedImages = submittedImages
      session.abortController = null
      try {
        await reconnectActiveRun(session)
        ElMessage.info('已同步会话状态，本次输入已保留在输入框。')
      } catch {
        session.historyLoadFailed = true
        ElMessage.warning('暂时无法核对运行状态，请重新加载会话。本次输入已保留。')
      }
      return
    }
    console.error('发送消息失败:', error)
    setRunStatus(ensureAgent(msg), 'error')
    msg.content = error.message || '处理失败，请稍后重试。'
    ElMessage.error(error.message || '请求失败')
  } finally {
    stopTimingSelection()
    timing.dispose()
    finishSession(session, operation)
  }
}

// SSE流式接收，标准SSE解析
async function streamChat(message: string, imagePaths: string[], msg: ChatMessage, session: Session, timing: ReturnType<typeof createDeliveryTiming>) {
  const token = localStorage.getItem('token')
  session.abortController = new AbortController()
  
  const body: Record<string, any> = {
    requestId: crypto.randomUUID(),
    message: message || '',
    conversationId: session.conversationId
  }
  if (session.originArticleId) body.originArticleId = session.originArticleId
  if (imagePaths.length > 0) {
    body.imagePaths = imagePaths
  }
  
  const response = await authenticatedFetch('/api/agent/chat/stream', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify(body),
    signal: session.abortController.signal
  })
  
  await consumeAgentStream(response, msg, session, timing)
}

function ensureAgent(msg: ChatMessage): AgentStreamState {
  return msg.agent ||= createAgentState()
}

async function consumeAgentStream(response: Response, msg: ChatMessage, session: Session, timing?: ReturnType<typeof createDeliveryTiming>) {
  const controller = session.abortController!
  let finished = false
  let runId = ''
  let after = '0'
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      for await (const data of readSse(response)) {
        if (!mounted || controller.signal.aborted) throw new DOMException('已停止接收', 'AbortError')
        if (data.startsWith('__EVENT_ID__:')) {
          after = data.substring('__EVENT_ID__:'.length).trim()
          continue
        }
        if (data === '[DONE]') { finished = true; continue }
        if (data.startsWith('[ERROR]')) {
          if (msg.provisional) {
            msg.content = ''
            msg.provisional = false
            ensureAgent(msg).answerReceiving = false
          }
          const error = new Error(data.substring(7).trim())
          Object.assign(error, { terminal: true })
          throw error
        }
        if (data.startsWith('__RUN_ID__:')) {
          runId = data.substring('__RUN_ID__:'.length).trim()
          if (session.conversationId) trackAiRun(runId, session.conversationId)
        }
        if (data.startsWith('__CONV_ID__:')) {
          const id = data.substring('__CONV_ID__:'.length).trim()
          const isNew = !session.conversationId
          bindConversationId(sessions, session, id)
          if (runId) trackAiRun(runId, id)
          if (activeSession.value === session) persistSelection(id)
          if (isNew && !props.embedded) loadConversations()
        } else if (handleResultEvent(data, msg, session)) {
          // Both live and replay streams use the same state transitions.
        } else if (data.startsWith('__PROGRESS__:')) {
          handleProgress(msg, data.substring('__PROGRESS__:'.length).trim(), session)
        } else if (!data.startsWith('__') && !(data.startsWith('{') && data.includes('conversationId'))) {
          msg.content += data.replace(/\\n/g, '\n')
        }
        if (activeSession.value !== session) timing?.invalidate()
        if (activeSession.value === session) scrollToBottom()
        // Several events can arrive in one TCP read. Yield to rendering instead
        // of processing the entire buffer before Vue can paint any text.
        if (data.startsWith('__ANSWER__:') && activeSession.value === session) {
          await nextTick()
          if (typeof requestAnimationFrame === 'function' && document.visibilityState === 'visible') {
            await new Promise<void>(resolve => {
              const frame = requestAnimationFrame(() => { clearTimeout(fallback); resolve() })
              // Hiding the tab can suspend animation frames after scheduling.
              const fallback = setTimeout(() => { cancelAnimationFrame(frame); resolve() }, 50)
            })
          }
          if (timing && runId && msg.content.trim()) {
            const list = messageListRef.value
            const bubble = list?.querySelector<HTMLElement>(`[data-virtual-key="${CSS.escape(msg.itemId || msg.messageId || '')}"] .message-bubble`)
            const bounds = bubble?.getBoundingClientRect(), viewport = list?.getBoundingClientRect()
            const visible = !!bounds && !!viewport && bounds.height > 0 && bounds.width > 0 &&
              bounds.bottom > Math.max(viewport.top, 0) && bounds.top < Math.min(viewport.bottom, window.innerHeight)
            const firstAnswerMs = timing.sample(visible)
            if (firstAnswerMs !== null) void request.post(`/agent/runs/${runId}/delivery-metrics`, { firstAnswerMs }).catch(() => {})
          }
        }
      }
      if (finished) return
      throw new Error('连接提前结束')
    } catch (error: any) {
      if (error.name === 'AbortError' || error.terminal || !runId || attempt === 3) {
        if (error.name !== 'AbortError' && runId) {
          try {
            const status: any = await request.get(`/agent/runs/${runId}`)
            msg.recoverable = !!status.data?.recoverable
          } catch { /* Keep the original stream error if status is unavailable. */ }
        }
        throw error
      }
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)))
      if (!mounted || controller.signal.aborted) throw new DOMException('已停止', 'AbortError')
      timing?.invalidate()
      response = await authenticatedFetch(`/api/agent/runs/${runId}/events?after=${after}`, {
        headers: { Accept: 'text/event-stream' }, signal: controller.signal,
      })
    }
  }
}

async function reconnectActiveRun(session: Session = activeSession.value) {
  const cid = session.conversationId
  if (!cid) return
  const windowVersion = session.historyVersion
  // The server owns the active run. Tab-local storage disappears when a tab closes.
  const response = await request.get(`/agent/conversations/${cid}/run`)
  if (!mounted || session.conversationId !== cid || session.abortController || session.cancelling) return
  if (windowVersion !== session.historyVersion && session.historyWindow.hasNewer) return
  const run = response.data
  if (!run) return
  const rid = run.runId
  for (const msg of session.messages) if (msg.runId !== rid) msg.recoverable = false
  const failedMessage = [...session.messages].reverse().find(msg => msg.role === 'assistant' && msg.runId === rid)
  if (failedMessage) failedMessage.recoverable = !!run.recoverable
  const preview = session.messages.find(msg => msg.interrupted && msg.interruptPayload?.runId === rid)
  if (preview && run.status !== 'running') {
    const recovered = approvalRecovery(run)
    preview.interrupted = recovered.interrupted
    preview.approvalNotice = recovered.notice
    preview.agent ||= createAgentState()
    setRunStatus(preview.agent, recovered.status)
    if (recovered.articleId) preview.draftArticleId = recovered.articleId
    if (recovered.payload) {
      preview.interruptPayload = recovered.payload
      preview.citations = recovered.payload.citations || preview.citations || []
      preview.content = recovered.payload.draft || preview.content
    }
  }
  if (run.status === 'awaiting_approval') {
    const payload = run.result?.interrupted
    if (payload && !session.messages.some(msg => msg.interrupted && msg.interruptPayload?.runId === rid)) {
      session.messages.push({ role: 'assistant', content: payload.draft || '', runId: rid,
        interrupted: true, interruptPayload: payload, isDraft: true, citations: payload.citations || [] })
    }
    return
  }
  if (run.status !== 'running') {
    if (run.status === 'succeeded' && run.result?.reply && (preview || failedMessage || session.messages.at(-1)?.role === 'user')) {
      const reply = preview || failedMessage || { role: 'assistant' as const, content: '', runId: rid }
      Object.assign(reply, { content: run.result.reply, interrupted: false, isDraft: false,
        articles: run.result.articles || [], citations: run.result.citations || [], draftArticleId: run.draftArticleId || undefined })
      setRunStatus(ensureAgent(reply), run.result.delivery_status === 'incomplete' ? 'error' : 'complete')
      if (!preview && !failedMessage) session.messages.push(reply)
    }
    if (run.status === 'cancelled' && failedMessage) {
      failedMessage.interrupted = false
      failedMessage.recoverable = false
      if (!failedMessage.content || failedMessage.provisional) failedMessage.content = '已停止处理。'
      failedMessage.provisional = false
      setRunStatus(ensureAgent(failedMessage), 'cancelled')
    }
    if (['failed', 'expired', 'cancelled'].includes(run.status) && session.messages.at(-1)?.role === 'user') {
      // The run may terminate between the history read and this status read.
      // Re-read its durable projection instead of losing activities in a generic notice.
      try {
        const history = await request.get(`/agent/conversations/${cid}/messages`, { params: { limit: 20 } })
        if (!mounted || session.conversationId !== cid || session.abortController || session.cancelling) return
        const page = historyPage(history.data)
        if (!session.historyWindow.hasNewer && history.code === 200 && page.items.some((msg: any) => msg.runId === rid)) {
          session.messages = page.items.map(toChatMessage)
          const { items: _, ...window } = page
          session.historyWindow = window
          const restored = session.messages.find(msg => msg.runId === rid)
          if (restored) restored.recoverable = !!run.recoverable
          return
        }
      } catch { /* Preserve the terminal outcome even if history cannot be reloaded. */ }
      if (!mounted || session.conversationId !== cid || session.abortController || session.cancelling) return
      session.messages.push({ role: 'assistant', runId: rid, recoverable: !!run.recoverable,
        content: run.status === 'cancelled' ? '上次生成已停止，可以重新发送请求。' : '上次生成已中断或超时，已释放运行，可以重新发送请求。' })
    }
    return
  }
  // Reloaded pages replay from zero because partial message content lived in memory.
  if (!failedMessage) session.messages.push({ role: 'assistant', itemId: `run:${rid}`, content: '', runId: rid, agent: createAgentState() })
  const msg = failedMessage || session.messages.at(-1)!
  session.liveMessages = session.messages.slice(-2)
  const operation = beginChatOperation(session)
  session.abortController = new AbortController()
  try {
    const response = await authenticatedFetch(`/api/agent/runs/${rid}/events?after=0`, {
      headers: { Accept: 'text/event-stream' }, signal: session.abortController.signal,
    })
    await consumeAgentStream(response, msg, session)
  } catch (error: any) {
    if (error.name !== 'AbortError' && mounted) {
      setRunStatus(ensureAgent(msg), 'error')
      if (msg.provisional) {
        msg.content = '生成未完成，请重新尝试。'
        msg.provisional = false
        ensureAgent(msg).answerReceiving = false
      }
      ElMessage.error(error.message || '恢复运行失败')
    }
  } finally { finishSession(session, operation) }
}

async function recoverReadOnlyRun(msg: ChatMessage) {
  const session = activeSession.value
  if (!msg.runId || session.loading || session.resuming || session.cancelling) return
  const index = session.messages.indexOf(msg)
  if (index < 0) return
  const operation = beginChatOperation(session)
  session.liveMessages = [msg]
  session.abortController = new AbortController()
  try {
    const response = await authenticatedFetch(`/api/agent/runs/${msg.runId}/recover`, {
      method: 'POST', headers: { Accept: 'text/event-stream' }, signal: session.abortController.signal,
    })
    if (!response.ok) {
      await response.body?.cancel()
      if (response.status === 409 || response.status === 404) msg.recoverable = false
      throw new Error(response.status === 409 ? '该任务已无法恢复，请重新提问。' : '任务恢复失败，请稍后重试。')
    }
    msg.content = ''
    msg.recoverable = false
    msg.agent = createAgentState()
    await consumeAgentStream(response, msg, session)
  } catch (error: any) {
    if (error.name !== 'AbortError') ElMessage.warning(error.message || '任务恢复失败')
  } finally { finishSession(session, operation) }
}

function handleProgress(msg: ChatMessage, progress: string, session: Session) {
  const state = ensureAgent(msg)
  if (progress === 'done') {
    if (!['error', 'cancelled', 'awaiting'].includes(state.status)) setRunStatus(state, 'complete')
    return
  }
  if (state.richEvents) return
  const label = progress === 'planner' ? '理解请求' : progress === 'synthesizer' ? '整理回答' : '处理资料'
  for (const item of state.activities) if (item.status === 'active') item.status = 'done'
  state.activities.push({ id: `legacy/${state.activities.length}`, label, status: 'active', startedAt: Date.now() })
}

// 发送快捷问题
function sendQuickQuestion(question: string) {
  userInput.value = question
  sendMessage()
}

// 暂停生成
async function handleCancel() {
  const session = activeSession.value
  if (!session.conversationId || session.cancelling) return
  session.cancelling = true
  const controller = session.abortController
  const operation = ++session.operation
  // Free the browser's HTTP connection before issuing the control request.
  // Disconnecting SSE does not cancel the durable server execution.
  controller?.abort()
  session.abortController = null
  session.streaming = false
  const syncStatus = () => {
    session.cancelling = false
    session.loading = true
    void reconnectActiveRun(session).catch(() => {
      ElMessage.warning('暂时无法确认停止结果，请重新加载会话查看运行状态。')
    }).finally(() => finishSession(session, operation))
  }
  try {
    // 1. 通知后端取消
    const response = await request.post(`/agent/chat/${session.conversationId}/cancel`)
    if (response.data?.status === 'saving') {
      ElMessage.info(response.data.message || '草稿正在保存，完成后可在草稿箱查看')
      syncStatus()
      return
    }
    if (['succeeded', 'failed', 'expired'].includes(response.data?.status)) { syncStatus(); return }
    if (response.data?.status === 'draft_saved') {
      const msg = [...(session.liveMessages.length ? session.liveMessages : session.messages)].reverse().find(item => item.role === 'assistant')
      if (msg) {
        msg.draftArticleId = response.data.draftArticleId
        msg.content = '草稿已保存到草稿箱，可继续编辑。'
      }
    }
  } catch (e) {
    console.error('暂停失败:', e)
    ElMessage.info('停止请求尚未确认，正在同步运行状态。')
    syncStatus()
    return
  }
  const latest = [...(session.liveMessages.length ? session.liveMessages : session.messages)].reverse().find(item => item.role === 'assistant')
  if (latest?.agent) {
    latest.interrupted = false
    setRunStatus(latest.agent, latest.draftArticleId ? 'complete' : 'cancelled')
    if (!latest.content) latest.content = latest.draftArticleId ? '草稿已保存到草稿箱，可继续编辑。' : '已停止处理。'
  }
  session.cancelling = false
  finishSession(session, operation)
}

// Human-in-the-loop 恢复（确认/拒绝）
async function copyEditedDraft(msg: ChatMessage) {
  const draft = (!msg.interrupted && msg.editedDraft) || msg.draftBackup || msg.editedDraft
  if (!draft) return
  try {
    const html = renderDraftPreview(draft.content, draft.content_format, msg.interruptPayload?.citations || msg.citations)
    const body = new DOMParser().parseFromString(html, 'text/html').body
    body.querySelectorAll('br').forEach(node => node.replaceWith('\n'))
    body.querySelectorAll('p,h1,h2,h3,h4,h5,h6,li,pre,tr,blockquote').forEach(node => node.append('\n\n'))
    await navigator.clipboard.writeText(`# ${draft.title}\n\n${draft.summary}\n\n${body.textContent?.trim() || ''}`)
    ElMessage.success('已复制修改内容，可粘贴到文章编辑器')
  } catch { ElMessage.warning('复制失败，请选中预览正文手动复制') }
}
async function handleResume(action: string, msg: ChatMessage) {
  const session = activeSession.value
  if (!session.conversationId || session.resuming || session.loading || session.cancelling) return
  if(action!=='reject' && msg.editedDraft){const error=draftEditError(msg.editedDraft);if(error){ElMessage.warning(error);return}}
  session.resuming = true
  const preview = { content: msg.content, isDraft: msg.isDraft, interrupted: msg.interrupted }
  const approvalConversation = session.conversationId
  const approvalRun = msg.interruptPayload?.runId
  const approvalHash = msg.interruptPayload?.draftHash
  msg.approvalNotice = ''

  // ─── 就地覆盖模式 ───
  // 不新建 assistant 消息，直接在当前这条 interrupt 气泡上更新：
  //   - 隐藏审批按钮
  //   - 撕掉"草稿预览"徽章
  //   - 清空旧 draft 内容，让 resume 流式 content += 时从空串开始拼
  // 这样"同一个气泡状态流转"，切会话回来也能和后端 ai_message 表一一对应
  msg.interrupted = false
  msg.isDraft = false
  msg.content = ''
  if (msg.agent) setRunStatus(msg.agent, 'working')

  const aiMsgIndex = session.messages.indexOf(msg)
  if (aiMsgIndex < 0) {
    console.error('handleResume: 找不到 msg 在 messages 里的位置')
    session.resuming = false
    return
  }

  const operation = beginChatOperation(session)
  session.liveMessages = [msg]
  if (activeSession.value === session) scrollToBottom(true)

  try {
    await streamResume(action, msg, session)
  } catch (error: any) {
    if (error.name === 'AbortError' || !mounted) return
    Object.assign(msg, preview)
    try {
      if (!approvalRun) throw new Error('审批运行缺失')
      const response = await request.get(`/agent/runs/${approvalRun}`)
      if (session.conversationId !== approvalConversation) return
      const recovered = approvalRecovery(response.data)
      msg.interrupted = recovered.interrupted
      msg.approvalNotice = recovered.notice
      setRunStatus(ensureAgent(msg), recovered.status)
      if (recovered.articleId) msg.draftArticleId = recovered.articleId
      if (recovered.payload) {
        if (recovered.payload.draftHash !== approvalHash && msg.editedDraft) {
          msg.draftBackup = msg.editedDraft
          msg.editedDraft = undefined
          msg.approvalNotice += ' 预览版本已变化，旧的手动修改已单独保留，可复制后合并到新版。'
        }
        msg.interruptPayload = recovered.payload
        msg.citations = recovered.payload.citations || msg.citations || []
        if (recovered.payload.draft) msg.content = recovered.payload.draft
      }
      if (recovered.status === 'working') {
        session.abortController = new AbortController()
        const events = await authenticatedFetch(`/api/agent/runs/${approvalRun}/events?after=0`, {
          headers: { Accept: 'text/event-stream' }, signal: session.abortController.signal,
        })
        await consumeAgentStream(events, msg, session)
      }
      if (error.name !== 'AbortError' && recovered.status !== 'working') {
        if (recovered.status === 'complete') ElMessage.success(recovered.notice)
        else ElMessage.warning(recovered.notice)
      }
    } catch {
      msg.interrupted = false
      msg.approvalNotice = '暂时无法核对审批状态，预览已保留。请重新加载会话后再操作。'
      if (session.conversationId === approvalConversation) setRunStatus(ensureAgent(msg), 'error')
      if (error.name !== 'AbortError') ElMessage.error(msg.approvalNotice)
    }
  } finally {
    finishSession(session, operation)
  }
}

// 跳转到草稿编辑页
async function editDraft(articleId: string) {
  try {
    const res = await request.get(`/article/${articleId}/edit`)
    await router.push(savedArticlePath(articleId, res.data?.status, res.data))
  } catch (error: any) {
    ElMessage.error(error.message || '文章已删除或无法访问')
  }
}

// SSE 流式 resume
async function streamResume(action: string, msg: ChatMessage, session: Session) {
  const token = localStorage.getItem('token')
  session.abortController = new AbortController()

  const response = await authenticatedFetch('/api/agent/chat/resume/stream', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify({
      conversationId: session.conversationId,
      action,
      runId: msg.interruptPayload?.runId,
      draftHash: msg.interruptPayload?.draftHash,
      editedDraft: action==='reject' ? undefined : msg.editedDraft
    }),
    signal: session.abortController.signal
  })

  await consumeAgentStream(response, msg, session)
}

function handleResultEvent(data: string, msg: ChatMessage, session: Session): boolean {
  const json = (prefix: string) => JSON.parse(data.substring(prefix.length))
  if (data.startsWith('__INPUT_ID__:')) {
    const id = data.substring('__INPUT_ID__:'.length).trim()
    const user = session.liveMessages.find(item => item.role === 'user')
    if (user) { user.messageId = id; user.turnId = id }
    msg.turnId = id
  } else if (data.startsWith('__AGENT_EVENT__:')) {
    applyAgentEvent(ensureAgent(msg), json('__AGENT_EVENT__:'))
  } else if (data.startsWith('__PREVIEW__:')) {
    // Old persisted runs may replay provisional tokens. Wait for the settled
    // answer or the verified approval draft rather than displaying a candidate.
    return
  } else if (data.startsWith('__ANSWER__:')) {
    msg.content = applyAnswerChunk(ensureAgent(msg), msg.content, json('__ANSWER__:'))
  } else if (data.startsWith('__RUN_ID__:')) {
    const runId = data.substring('__RUN_ID__:'.length).trim()
    msg.runId = runId
  } else if (data.startsWith('__STAGE__:')) {
    const state = ensureAgent(msg)
    if (!state.richEvents) {
      const payload = json('__STAGE__:')
      state.activities.push({ id: `stage/${payload.stage}`, label: `已完成 ${payload.stage}/${payload.total} 个阶段`, status: 'done' })
    }
  } else if (data.startsWith('__REPLY__:')) {
    msg.content = json('__REPLY__:').content
    msg.provisional = false
    ensureAgent(msg).answerReceiving = false
  } else if (data.startsWith('__CITATIONS__:')) {
    msg.citations = json('__CITATIONS__:')
  } else if (data.startsWith('__ARTICLES__:')) {
    msg.articles = json('__ARTICLES__:')
  } else if (data.startsWith('__INTERRUPTED__:')) {
    const payload = json('__INTERRUPTED__:')
    msg.editedDraft = undefined
    if (payload.draft) { msg.content = payload.draft; msg.isDraft = true }
    msg.interrupted = true
    msg.provisional = false
    ensureAgent(msg).answerReceiving = false
    msg.interruptPayload = payload
    msg.citations = payload.citations || msg.citations || []
    msg.draftRevision = ''
    setRunStatus(ensureAgent(msg), 'awaiting')
  } else if (data.startsWith('__DRAFT_SAVED__:')) {
    const payload = json('__DRAFT_SAVED__:')
    msg.draftArticleId = payload.draftArticleId
    msg.draftTitle = payload.title || ''
    msg.isDraft = false
  } else return false
  return true
}

// Enter 发送；Shift+Enter 交给浏览器在光标处原生换行
function handleEnterKey(event: KeyboardEvent) {
  // 输入法组合输入时的回车用于选词，不能发送
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  sendMessage()
}

// 输入框随内容长高，达到 CSS max-height 后才在内部滚动
function resizeInput() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  const maxHeight = parseFloat(getComputedStyle(el).maxHeight)
  const contentHeight = el.scrollHeight
  const nextHeight = Number.isFinite(maxHeight) ? Math.min(contentHeight, maxHeight) : contentHeight
  el.style.height = `${nextHeight}px`
  el.style.overflowY = contentHeight > nextHeight ? 'auto' : 'hidden'
}

// 发送后清空、快捷问题填入等程序化修改同样需要重新计算高度
watch(userInput, () => nextTick(resizeInput))

// 滚动到底部
// force=true 时无视 autoScrollToBottom，强制贴底并恢复自动跟随（用于用户主动发送消息、切会话、恢复中断等场景）
function scrollToBottom(force = false) {
  if (activeSession.value.historyWindow.hasNewer) return
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
  autoScrollToBottom.value = !activeSession.value.historyWindow.hasNewer && distanceToBottom < SCROLL_BOTTOM_THRESHOLD
}

function handleHistoryWheel(event: WheelEvent) {
  if (event.deltaY < 0 && (messageListRef.value?.scrollTop || 0) < 80 &&
      activeSession.value.historyWindow.hasOlder && !activeSession.value.historyBusy) void showEarlierMessages()
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

function renderDraftPreview(content: string, format?: string, citations: SourceLink[] = []): string {
  return draftBodyHtml(safeHtml(format === 'html' ? content : renderChatMarkdown(preprocessMarkdown(content))), citations)
}

function renderMarkdown(content: string, citations: SourceLink[] = []): string {
  if (!content) return ''
  
  // 流式进行中不使用缓存（content 持续变化）
  const cacheKey = JSON.stringify([content, citations.map(c => [c.id, c.articleId, c.url, c.title])])
  if (!streaming.value) {
    const cached = renderedCache.get(cacheKey)
    if (cached) return cached
  }
  
  let processed = preprocessMarkdown(content)
  
  // 流式进行中，保护不完整的表格
  if (streaming.value) {
    processed = protectIncompleteTable(processed)
  }
  
  const rendered = formatCitationHtml(safeHtml(renderChatMarkdown(processed)), citations)
  
  // 非流式状态下缓存结果（历史消息）
  if (!streaming.value) {
    renderedCache.set(cacheKey, rendered)
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
  releaseChatSessions(sessions.values())
  sessions.clear()
  activeSession.value = newSession()
  historyLoadVersion += 1
  currentConversationId.value = null
  messages.value = []
  persistSelection(null)
  requestLogin()
}

function requestLogin() {
  if (props.embedded) emit('loginRequired')
  else showLoginDialog.value = true
}

async function initializeConversation() {
  if (!localStorage.getItem('token')) { requestLogin(); return }
  const version = ++historyLoadVersion
  loadingMessages.value = true
  historyLoadFailed.value = false
  try {
    if (props.embedded) {
      // Merely opening the drawer only reads the latest chat. The stream request
      // creates a conversation when the user actually sends their first question.
      currentOriginArticleId.value = props.originArticleId || null
      currentOriginArticleTitle.value = props.originArticleTitle
      const res = await request.get('/agent/conversations', { params: { scope: 'article', originArticleId: props.originArticleId, limit: 1 } })
      if (!mounted || version !== historyLoadVersion) return
      if (res.code !== 200 || !Array.isArray(res.data)) throw new Error('无法加载会话')
      if (res.data.length) await switchConversation(res.data[0])
    } else {
      const queryId = typeof route.query.conversationId === 'string' ? route.query.conversationId : null
      const queryArticleId = typeof route.query.originArticleId === 'string' ? route.query.originArticleId : null
      const key = selectionStorageKey()
      const id = queryId || (!queryArticleId && key ? localStorage.getItem(key) : null)
      if (id) {
        const res = await request.get(`/agent/conversations/${encodeURIComponent(id)}`)
        if (!mounted || version !== historyLoadVersion) return
        if (res.code !== 200 || !res.data) throw new Error('无法加载会话')
        await switchConversation(res.data)
      } else if (queryArticleId) {
        currentConversationId.value = null
        currentOriginArticleId.value = queryArticleId
        currentOriginArticleTitle.value = '当前文章'
        messages.value = []
        articleGroupOpen.value = true
      }
    }
  } catch {
    if (mounted && version === historyLoadVersion) {
      historyLoadFailed.value = true
      // Never silently turn a failed restore into a new conversation.
      ElMessage.error('对话无法加载，请重试或开启新对话')
    }
  } finally {
    if (mounted && (version === historyLoadVersion || !loadingMessages.value)) loadingMessages.value = false
  }
}

function expandInAssistant() {
  if (!currentConversationId.value) return
  router.push({ path: '/ai-chat', query: { conversationId: currentConversationId.value } })
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
  mounted = true
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  window.addEventListener('resize', handleResize)
  if (!localStorage.getItem('token')) {
    requestLogin()
    return
  }
  
  await Promise.all([loadConversations(), initializeConversation()])
})

watch(currentConversationId, id => { if (mounted) setViewedAiConversation(id) })

watch(() => route.query.conversationId, (id) => {
  if (mounted && !props.embedded && typeof id === 'string' && id !== currentConversationId.value) initializeConversation()
})

watch(() => props.originArticleId, () => {
  if (!mounted || !props.embedded) return
  createNewConversation()
  currentConversationId.value = null
  messages.value = []
  initializeConversation()
})

watch(() => props.originArticleTitle, title => {
  if (props.embedded) currentOriginArticleTitle.value = title
})

onUnmounted(() => {
  mounted = false
  libraryGeneration++;clearTimeout(librarySearchTimer)
  historyLoadVersion += 1
  releaseChatSessions(sessions.values())
  setViewedAiConversation(null)
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.sidebar-heading p { margin: 6px 0 0; color: var(--ej-muted); font-size: 12px; }
.conversation-search-wrap { display: flex; align-items: center; gap: 8px; margin: 4px 16px 12px; padding: 0 10px; min-height: 40px; border: 1px solid var(--ej-line); border-radius: 10px; background: var(--ej-surface); }
.conversation-search-wrap:focus-within { outline: 2px solid var(--ej-accent); outline-offset: 2px; }
.conversation-search-wrap > svg { width: 16px; height: 16px; flex-shrink: 0; color: var(--ej-muted); }
.conversation-search { flex: 1; min-width: 0; width: 0; padding: 10px 0; border: 0; background: transparent; font-size: 12px; color: var(--ej-ink); outline: 0; }
.conversation-search-clear { width: 24px; height: 24px; flex-shrink: 0; border: 0; border-radius: 5px; background: transparent; color: var(--ej-muted); font-size: 19px; cursor: pointer; }
.conversation-search-clear:hover { color: var(--ej-ink); background: var(--ej-soft); }
.sidebar-memory-link { display: flex; align-items: center; gap: 10px; flex-shrink: 0; margin: 8px 16px 16px; padding: 14px 2px 0; border-top: 1px solid var(--ej-line); text-decoration: none; color: var(--ej-ink); }
.sidebar-memory-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--ej-surface); font-size: 20px; }
.sidebar-memory-link > span:nth-child(2) { display: flex; flex: 1; flex-direction: column; gap: 4px; }
.sidebar-memory-link strong { font-size: 12px; font-weight: 600; }
.sidebar-memory-link small { color: var(--ej-muted); font-size: 10px; }
.sidebar-memory-link:hover strong { text-decoration: underline; text-underline-offset: 3px; }
.conv-run-status { color: var(--ej-ink); display: inline-flex; align-items: center; gap: 6px; }
.conv-run-status::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--studio-lime); border: 1px solid var(--ej-ink); }
.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.citation-link {
  background: transparent;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  padding: 4px 8px;
  color: var(--ej-accent);
  cursor: pointer;
  text-align: left;
}
.ai-chat-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  background: var(--ej-canvas);
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
  color: var(--ej-accent);
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
  border-color: var(--ej-accent);
  color: var(--ej-accent);
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
  background: var(--ej-accent);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.2s ease, transform 0.15s ease;
}

.new-chat-btn:hover {
  background: var(--ej-ink);
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
  gap: 0;
  padding: 0;
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
  background: var(--ej-accent-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.conv-icon svg {
  color: var(--ej-accent);
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
  position: static;
  flex-shrink: 0;
  background: none;
  border: none;
  cursor: pointer;
  opacity: 1;
  transition: opacity 0.2s;
  padding: 4px;
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
  background: var(--ej-accent-soft);
  overflow: hidden;
}

.message-avatar svg {
  width: 24px;
  height: 24px;
  color: var(--ej-accent);
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
  background: var(--ej-accent);
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
  box-shadow: 0 6px 20px rgba(17, 17, 15, 0.12);
  border-color: var(--ej-ink);
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
  color: var(--ej-accent);
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

/* Markdown样式；代码块与行内代码统一使用 styles/theme.css 中的墨色代码块 */
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
  border-left: 3px solid var(--ej-accent);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--ej-muted);
}

.message-bubble :deep(a) {
  color: var(--ej-accent);
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
  border: 1px solid var(--ej-hairline);
  padding: 6px 12px;
  text-align: left;
}

.message-bubble :deep(th) {
  background: var(--ej-canvas);
  font-weight: 600;
}

/* 流式传输中未完成的表格以等宽文本暂存，样式见 styles/theme.css 的 pre.streaming-table */

/* 加载动画 */
.typing-indicator {
  display: flex;
  gap: 5px;
  padding: 8px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--ej-accent);
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
.draft-review-card { width: min(100%, 720px); border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; overflow: hidden; margin-bottom: 12px; }
.draft-review-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 17px 20px; background: #f8f9fb; border-bottom: 1px solid #eceef1; }
.draft-review-eyebrow { font-size: 11px; color: var(--ej-muted); }
.draft-review-header h3 { font-size: 15px; color: var(--ej-ink); margin: 5px 0 0; font-weight: 700; }
.draft-review-status { font-size: 11px; padding: 4px 8px; white-space: nowrap; }
/* 草稿预览的代码块见 styles/theme.css */
.draft-review-body { max-height: 480px; overflow: auto; padding: 18px 22px; line-height: 1.8; font-size: 14px; color: #2f2d28; overflow-wrap: anywhere; }
.draft-review-body :deep(table) { width: 100%; border-collapse: collapse; }
.draft-review-body :deep(th), .draft-review-body :deep(td) { border: 1px solid var(--ej-hairline); padding: 8px; }
.draft-review-body :deep(th) { background: var(--ej-canvas); text-align: left; }
.draft-review-footer { padding: 16px 20px; border-top: 1px solid var(--ej-hairline); }
.draft-review-footer > p { color: var(--ej-muted); font-size: 12px; margin: 0 0 12px; }
.draft-revision { display: flex; align-items: flex-end; gap: 10px; margin-top: 14px; }
.draft-revision textarea { flex: 1; min-width: 0; border: 1px solid #e2e5ea; border-radius: 7px; padding: 10px; resize: vertical; font: inherit; font-size: 12px; outline: none; }
.draft-revision textarea:focus { border-color: #a0b2c8; }
.draft-revision > button { padding: 8px 11px; border: 1px solid #dce1e7; background: #f9fafb; border-radius: 7px; color: #586575; cursor: pointer; white-space: nowrap; }
.draft-revision > button:disabled { opacity: .5; cursor: default; }

.progress-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 18px;
  background: linear-gradient(180deg, #fafbfd 0%, var(--ej-canvas) 100%);
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
  border-top-color: var(--ej-accent);
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
  background: var(--ej-accent);
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
  background: var(--ej-accent);
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
  background: var(--ej-accent);
  color: white;
  border-color: var(--ej-accent);
  box-shadow: 0 2px 8px rgba(17, 17, 15, 0.25);
}

.interrupt-btn.approve:hover:not(:disabled) {
  background: var(--ej-ink);
  border-color: var(--ej-ink);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(17, 17, 15, 0.3);
}

.interrupt-btn.reject {
  background: white;
  color: #606266;
  border-color: #dcdfe6;
}

.interrupt-btn.reject:hover:not(:disabled) {
  background: var(--ej-canvas);
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
  background: var(--ej-accent);
  border-radius: 0 0 8px 8px;
  transition: width 0.2s ease;
}

.upload-progress-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--ej-accent);
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
  /* border-box：32px = 一行 24px + 上下各 4px 内边距；最多长到 7 行，之后内部滚动 */
  height: 32px;
  min-height: 32px;
  max-height: 176px;
  overflow-y: hidden;
  font-family: inherit;
  line-height: 24px;
  padding: 4px 0;
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
  background: var(--ej-accent);
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
  background: var(--ej-ink);
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
    padding: 0;
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
    padding: 0;
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
    height: 30px;
    min-height: 30px;
    max-height: 162px;
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
  color: var(--ej-accent);
  font-weight: 500;
  margin-left: auto;
  padding-left: 8px;
  border-left: 1px solid #edf0f3;
}

.draft-link-action svg {
  color: var(--ej-accent);
}
.conversation-group + .conversation-group { margin-top: 20px; }
.conversation-group-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 8px 12px; border: 0; background: transparent; color: var(--ej-muted); font-size: 12px; font-weight: 650; cursor: pointer; }
.conversation-group-toggle svg { width: 12px; height: 12px; transition: transform 160ms; }
.conversation-group-toggle svg.expanded { transform: rotate(90deg); }
.conv-article-title { color: var(--ej-muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 4px; }
.conversation-load-more { width: 100%; padding: 10px; background: transparent; border: 0; color: var(--ej-muted); cursor: pointer; font-size: 12px; }
.article-context-strip { display: flex; align-items: center; gap: 10px; padding: 12px 24px; border-bottom: 1px solid #11110f18; flex-shrink: 0; font-size: 12px; min-width: 0; }
.article-context-strip > span { color: var(--ej-muted); flex-shrink: 0; }
.article-context-strip button { background: transparent; border: 0; padding: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; cursor: pointer; color: var(--ej-ink); }
.article-context-strip small { color: var(--ej-muted); margin-left: auto; flex-shrink: 0; }
.history-error { padding: 12px 20px; color: #9b482f; font-size: 13px; background: #fff1e8; }
.history-error button { border: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; margin-left: 8px; }
.article-chat-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px 18px 14px; flex-shrink: 0; }
.article-chat-heading { display: flex; align-items: center; gap: 10px; }
.article-chat-heading strong { display: block; font-size: 15px; }
.article-chat-heading div > span { display: block; font-size: 11px; color: var(--ej-muted); margin-top: 4px; }
.article-chat-mark { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--ej-ink); background: var(--ej-lime, #caff4d); display: grid; place-items: center; font-size: 21px; }
.article-chat-controls { display: flex; align-items: center; gap: 4px; }
.article-chat-controls button { background: transparent; border: 0; border-radius: 8px; padding: 6px 8px; cursor: pointer; font-size: 12px; color: var(--ej-muted); }
.article-chat-controls button:hover { background: #11110f08; color: var(--ej-ink); }
.article-chat-controls .article-chat-close { font-size: 23px; line-height: 1; }
.article-reader-link { display: flex; align-items: center; gap: 8px; padding: 8px 18px 12px; background: transparent; border: 0; border-bottom: 1px solid #11110f18; color: var(--ej-muted); font-size: 12px; text-align: left; cursor: pointer; flex-shrink: 0; }
.reader-link-arrow { margin-left: auto; }
.reader-unread-dot { width: 6px; height: 6px; border-radius: 50%; background: #e66d55; }
.expand-assistant-link { display: block; margin: 12px auto 0; padding: 0; border: 0; background: transparent; font-size: 11px; color: var(--ej-muted); cursor: pointer; }
.expand-assistant-link:disabled { cursor: default; opacity: .4; }
:global(#app .ai-chat-page.embedded-chat) { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ej-surface); overflow: hidden; border-radius: inherit; }
:global(#app .ai-chat-page.embedded-chat::before) { display: none; }
:global(#app .embedded-chat .chat-container) { padding: 0; height: auto; min-height: 0; flex: 1; width: 100%; max-width: none; margin: 0; }
:global(#app .embedded-chat .chat-main) { width: 100%; min-width: 0; min-height: 0; background: transparent; }
:global(#app .embedded-chat .article-context-strip) { padding: 10px 18px; background: #11110f03; }
:global(#app .embedded-chat .welcome-area) { min-height: 0; padding: 28px 20px; }
:global(#app .embedded-chat .welcome-title) { font-size: 21px; line-height: 1.5; letter-spacing: -.02em; }
:global(#app .embedded-chat .welcome-desc) { font-size: 13px; line-height: 1.7; margin-bottom: 20px; }
:global(#app .embedded-chat .welcome-eyebrow) { font-size: 11px; }
:global(#app .embedded-chat .quick-questions) { max-width: none; gap: 8px; }
:global(#app .embedded-chat .quick-question-item) { padding: 10px 0; font-size: 13px; }
:global(#app .embedded-chat .message-list) { padding: 20px 16px; flex: 1; min-height: 0; overflow-y: auto; }
:global(#app .embedded-chat .message-item) { gap: 9px; margin-bottom: 22px; }
:global(#app .embedded-chat .message-avatar) { width: 28px; height: 28px; flex-shrink: 0; }
:global(#app .embedded-chat .message-content) { max-width: calc(100% - 37px); min-width: 0; font-size: 13px; }
:global(#app .embedded-chat .message-bubble) { font-size: 13px; line-height: 1.85; overflow-wrap: anywhere; }
:global(#app .ai-chat-page.embedded-chat .article-card) { padding: 12px; min-height: 0; border-radius: 12px; }
:global(#app .embedded-chat .article-cards) { gap: 8px; margin-top: 10px; }
:global(#app .embedded-chat .card-title) { font-size: 12px; }
:global(#app .embedded-chat .card-cover) { width: 58px; height: 52px; }
:global(#app .embedded-chat .input-area) { flex-shrink: 0; padding: 14px 16px; }
:global(#app .embedded-chat .input-wrapper) { padding: 10px; gap: 8px; border-radius: 15px; }
:global(#app .embedded-chat .input-wrapper textarea) { font-size: 13px; min-height: 24px; padding: 0; }
:global(#app .embedded-chat .input-wrapper .send-btn) { width: 31px; height: 31px; }
:global(#app .embedded-chat .input-tips) { font-size: 10px; margin-top: 8px; }
:global(#app .embedded-chat .tip-note) { display: none; }
@media (max-width: 768px) { .article-context-strip small { display: none; } }
</style>
