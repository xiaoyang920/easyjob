<template>
  <div :class="['article-detail-page', { 'ai-question-open': showAiQuestion }]">
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
      <div class="nav-right">
        <button class="nav-btn" @click="goBackOr(router, '/')">返回</button>
        <button v-if="isAuthor" class="nav-btn primary" @click="editArticle">编辑</button>
        <button v-if="isAuthor" class="nav-btn danger" @click="deleteArticle">删除</button>
      </div>
    </nav>

    <!-- 主容器 -->
    <div class="main-container">
      <!-- 左侧目录 -->
      <aside
        ref="tocRef"
        class="toc-sidebar"
        @pointerenter="tocHovered = true"
        @pointerleave="tocHovered = false"
      >
        <div class="toc-title">文章目录</div>
        <ul v-if="tocItems.length > 0" class="toc-list">
          <li
            v-for="(item, index) in tocItems"
            :key="index"
            :class="['toc-item', `level-${item.level}`, { active: activeHeading === item.id }]"
          >
            <a :href="`#${item.id}`" @click.prevent="scrollToHeading(item.id)">
              {{ item.text }}
            </a>
          </li>
        </ul>
        <div v-else class="toc-empty">
          本文暂无目录
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="main-content">
        <!-- 文章卡片 -->
        <article class="article-card">
          <!-- 文章头部 -->
          <header class="article-header">
            <h1 class="article-title">{{ article.title }}</h1>
            
            <!-- 分类和标签 -->
            <div v-if="article.category || (article.tags && article.tags.length > 0)" class="article-tags-section">
              <span v-if="article.category" class="category-badge">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                  <path d="M17.63 5.84C17.27 5.33 16.67 5 16 5L5 5.01C3.9 5.01 3 5.9 3 7v10c0 1.1.9 1.99 2 1.99L16 19c.67 0 1.27-.33 1.63-.84L22 12l-4.37-6.16z"/>
                </svg>
                {{ article.category.categoryName }}
              </span>
              <span 
                v-for="tag in article.tags" 
                :key="tag.tagId"
                class="tag-badge"
              >
                #{{ tag.tagName }}
              </span>
            </div>
            
            <div class="article-meta">
              <div class="meta-item">
                <img 
                  :src="getAvatarUrl(article.authorAvatar)" 
                  alt="作者头像" 
                  class="author-avatar"
                  @error="handleAvatarError"
                >
                <span class="author-name" @click="goToUserSpace(article.authorId)">
                  {{ article.authorName }}
                </span>
              </div>
              <div class="meta-item">
                <span>{{ formatDate(article.publishTime) }}</span>
              </div>
              <div class="meta-item">
                <span>{{ article.viewCount || 0 }} 阅读</span>
              </div>
              <span v-if="article.isOriginal" class="original-badge">原创</span>
            </div>
          </header>

          <!-- 封面图 -->
          <img 
            v-if="article.coverImage" 
            :src="getImageUrl(article.coverImage)" 
            alt="封面" 
            class="article-cover"
            @click="previewImage = getImageUrl(article.coverImage)"
            @error="handleCoverError"
          >

          <!-- 文章摘要 -->
          <div v-if="article.summary" class="article-summary">
            {{ article.summary }}
          </div>

          <!-- 文章内容 -->
          <div v-if="article.canReadFull !== false" class="article-content" v-html="safeHtml(article.content)" ref="contentRef"></div>
          <div v-else class="reading-lock">
            <span class="reading-level-badge">L{{ article.requiredLevel }} 阅读内容</span>
            <h2>继续阅读，解锁这篇文章</h2>
            <p>你的阅读等级为 L{{ article.readerLevel || 0 }}，还需累计有效阅读 {{ readingDuration(article.secondsToUnlock || 0) }}。</p>
            <button class="nav-btn primary" @click="myUserId ? router.push('/') : showLoginDialog = true">{{ myUserId ? '去阅读公开文章' : '登录并开始累计' }}</button>
          </div>
          <div v-if="article.viewerAdmin" class="reading-admin">
            <label for="article-reading-level">最低阅读等级</label>
            <select id="article-reading-level" v-model.number="selectedReadingLevel" :disabled="savingReadingLevel">
              <option v-for="rule in article.readingProgress?.rules || []" :key="rule.level" :value="rule.level">L{{ rule.level }}{{ rule.level === 0 ? ' · 公开' : '' }}</option>
            </select>
            <button class="nav-btn" :disabled="savingReadingLevel || selectedReadingLevel === article.requiredLevel" @click="saveReadingLevel">{{ savingReadingLevel ? '保存中…' : '保存' }}</button>
            <span role="status">{{ readingLevelFeedback }}</span>
          </div>
        </article>

        <!-- 互动区域 -->
        <div class="action-bar">
          <div class="action-btn-group">
            <button 
              :class="['action-btn like-btn', { active: article.hasLiked }]" 
              @click="toggleLike"
            >
              <svg class="action-icon" viewBox="0 0 1024 1024">
                <path d="M939.358251 423.424662c-23.01825-37.252439-62.924121-60.779272-107.019409-63.209624-2.755764-0.38681-5.510504-0.579191-8.347109-0.579191l-152.202471-0.121773c6.649444-28.975938 10.015098-58.653865 10.015098-88.657202 0-28.223808-3.213181-57.139372-9.556657-85.952604-0.447185-2.043542-1.098008-4.006244-1.932002-5.866614-15.820314-57.302077-67.37755-96.841605-127.282918-96.841605-72.827679 0-132.081201 59.254545-132.081201 132.081201 0 3.334955 0.132006 6.66991 0.406253 10.015098-2.196015 57.211003-32.108279 109.947088-80.269162 141.363611-14.447037 9.42465-18.524912 28.773324-9.099239 43.220361 9.414417 14.437827 28.752858 18.535145 43.220361 9.099239 65.811892-42.925648 106.429984-115.325585 108.656699-193.684234 0.030699-1.332345-0.010233-2.663666-0.14224-3.996011-0.203638-2.012843-0.304945-4.016477-0.304945-6.019087 0-38.381146 31.233352-69.614497 69.614497-69.614497 32.57593 0 60.474326 22.204721 67.824735 53.997821 0.356111 1.534959 0.823761 3.019777 1.402953 4.453429 4.696975 22.814612 7.076162 45.579081 7.076162 67.743894 0 37.485753-6.222725 74.352405-18.494213 109.592001-3.324722 9.546424-1.819438 20.111037 4.02671 28.345582 5.856381 8.245801 15.332197 13.146415 25.448602 13.156648l193.226816 0.101307c1.423419 0.264013 2.857071 0.426719 4.300956 0.477884 24.116257 0.9967 45.935192 13.614066 58.603723 34.090423 7.838525 12.31242 11.438517 26.800389 10.431583 41.939181-0.080841 0.945535-0.121773 1.911536-0.11154 2.877537 0 0.854461 0.040932 1.697665 0.11154 2.53166 0.010233 0.335644-0.030699 0.661056-0.11154 0.976234-0.101307 0.376577-0.193405 0.772596-0.284479 1.159406l-74.972529 330.391802c-0.914836 1.281179-1.738597 2.6432-2.449795 4.046153-5.937223 11.762905-14.660908 21.48329-25.346271 28.172643-10.746762 6.812149-23.059182 10.614755-35.757388 11.06194-0.854461-0.061398-513.766226-0.224104-513.766226-0.224104-0.467651-0.020466-0.935302-0.030699-1.402953-0.030699 0 0-111.01542 0.172939-112.718201 0.457418-1.932002 0-3.446495-1.50426-3.446495-3.415796l0.299829-416.334173c0-1.901303 1.545192-3.446495 3.01466-3.456728l1.245364 0.121773c1.174756 0.132006 2.653433 0.284479 3.52836 0.193405l83.82822-0.222057 0 339.367221c0 17.253966 13.979386 31.233352 31.233352 31.233352s31.233352-13.979386 31.233352-31.233352L281.009092 435.350273c0-1.778506 0-8.631588 0-10.411117 0-17.253966-13.979386-30.928407-31.233352-30.928407-1.50426 0-117.547183 0.304945-119.402437 0.304945-36.34272 0-65.913199 29.566386-65.913199 65.893756l-0.299829 416.334173c0 36.337603 29.571503 65.902966 65.913199 65.902966 2.541893 0 111.406323-0.457418 111.406323-0.457418 0.457418 0.020466 0.925069 0.030699 1.382487 0.030699 0 0 511.458671 0.274246 512.505513 0.274246 25.469068 0 50.296523-7.197936 71.647807-20.73116 19.612687-12.281721 35.777855-29.881564 46.839795-50.967812 3.660366-5.622044 6.435573-11.875468 8.256034-18.615986 0.11154-0.416486 0.213871-0.823761 0.304945-1.240247l74.881454-330.340637c1.596358-6.212492 2.257413-12.586666 2.00261-18.992563C960.892707 473.366098 953.948551 446.331371 939.358251 423.424662z" :fill="article.hasLiked ? 'currentColor' : '#999999'"/>
                <path d="M450.027553 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C481.260905 532.629853 467.281519 518.650467 450.027553 518.650467z" :fill="article.hasLiked ? 'currentColor' : '#999999'"/>
                <path d="M693.805696 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C725.039048 532.629853 711.058638 518.650467 693.805696 518.650467z" :fill="article.hasLiked ? 'currentColor' : '#999999'"/>
                <path d="M648.940882 660.09492c-14.304797-9.393951-33.592073-5.398964-43.159986 8.763594-0.132006 0.193405-13.614066 19.754926-34.171264 19.754926-19.98824 0-32.423457-18.09717-33.266661-19.368116-9.17087-14.427594-28.254507-18.809391-42.834574-9.770528-14.650675 9.109472-19.155269 28.366048-10.055007 43.016723 11.214413 18.047028 41.96988 48.588625 86.156242 48.588625 43.962258 0 75.104535-30.318516 86.572728-48.222281C667.404396 688.461991 663.216004 669.500127 648.940882 660.09492z" :fill="article.hasLiked ? 'currentColor' : '#999999'"/>
              </svg>
              <span class="count">{{ article.likeCount || 0 }}</span>
            </button>
            <button class="action-btn coin-btn" @click="toggleCoin">
              <svg class="action-icon" viewBox="0 0 1024 1024">
                <path d="M488.727273 396.8V314.181818h-139.636364a23.272727 23.272727 0 0 1 0-46.545454h325.818182a23.272727 23.272727 0 1 1 0 46.545454h-139.636364v82.618182A232.727273 232.727273 0 0 1 744.727273 628.363636v23.272728a23.272727 23.272727 0 1 1-46.545455 0v-23.272728a186.181818 186.181818 0 0 0-162.909091-184.785454V791.272727a23.272727 23.272727 0 1 1-46.545454 0V443.578182A186.181818 186.181818 0 0 0 325.818182 628.363636v23.272728a23.272727 23.272727 0 1 1-46.545455 0v-23.272728a232.727273 232.727273 0 0 1 209.454546-231.563636zM512 977.454545C254.929455 977.454545 46.545455 769.070545 46.545455 512S254.929455 46.545455 512 46.545455s465.454545 208.384 465.454545 465.454545-208.384 465.454545-465.454545 465.454545z m0-46.545454a418.909091 418.909091 0 1 0 0-837.818182 418.909091 418.909091 0 0 0 0 837.818182z" fill="currentColor"/>
              </svg>
              <span class="count">{{ article.coinCount || 0 }}</span>
            </button>
            <button :class="['action-btn collect-btn', { active: article.hasCollected }]" @click="toggleCollect">
              <svg class="action-icon" viewBox="0 0 1059 1024">
                <path d="M253.488042 1024c-16.9 0-33.2875-5.1125-47.6125-15.3625-26.625-18.425-39.425-49.6625-34.3125-81.925l40.9625-251.9c1.5375-10.2375-1.5375-20.475-8.7-27.65L28.213042 466.4375c-22.0125-22.525-29.1875-55.3-19.45-84.9875 9.725-29.7 35.325-51.2 66.05-55.8125l237.575-36.35c10.75-1.5375 19.4625-8.1875 24.0625-17.925L441.388042 48.125c13.825-29.7 42.5-48.125 75.2625-48.125s61.4375 18.4375 75.2625 48.125l104.45 223.2375c4.6125 9.725 13.825 16.375 24.0625 17.925L958.000542 325.625a82.355 82.355 0 0 1 66.05 55.8125c10.2375 29.7 2.5625 62.4625-19.45 84.9875l-175.625 180.7375c-7.1625 7.175-10.2375 17.925-8.7 27.65l40.9625 251.9c5.125 31.75-8.1875 63.4875-34.3 81.925-26.1125 18.4375-59.9 20.4875-88.0625 4.6125l-206.85-114.6875c-9.725-5.1125-20.9875-5.1125-30.7125 0l-207.3625 115.2c-12.8125 6.65-26.6375 10.2375-40.4625 10.2375zM516.650542 51.2c-12.8 0-23.55 7.1625-29.1875 18.4375L383.525542 292.875c-11.775 25.0875-35.325 43.0125-62.975 47.1l-237.575 36.35c-12.2875 2.05-21.5 9.7375-25.6 21.5-4.1 11.775-1.025 24.0625 7.675 32.775L240.688042 611.325c18.4375 18.95 26.625 45.5625 22.525 71.675L222.250542 934.9125c-2.05 12.8 3.075 24.575 13.3125 31.7375 10.2375 7.175 23.0375 7.6875 33.7875 1.5375l207.3625-115.2c25.0875-13.825 55.3-13.825 80.3875 0l207.3625 115.2c10.75 6.1375 23.55 5.625 33.8-1.5375 10.2375-7.1625 15.3625-18.95 13.3125-31.7375L770.625542 683.0125c-4.1-26.1125 4.1-52.7375 22.525-71.675l175.625-180.7375c8.7-8.7 11.2625-20.9875 7.675-32.775-4.0875-11.775-13.3125-19.9625-25.6-21.5l-237.5625-36.35c-27.65-4.0875-51.2-22.0125-62.975-47.1L545.838042 69.6375c-5.625-11.2625-16.375-18.4375-29.1875-18.4375z m0 0" :fill="article.hasCollected ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="30"/>
              </svg>
              <span class="count">{{ article.collectCount || 0 }}</span>
            </button>
            <button class="action-btn share-btn" @click="shareArticle">
              <svg class="action-icon" viewBox="0 0 1236 1024">
                <path fill="currentColor" d="M741.743 1018.343c-28.287 0-50.917-11.315-73.547-28.288-22.63-22.63-39.602-50.917-39.602-84.862V792.044c-124.464 0-328.133 33.945-435.624 181.039-16.973 28.287-56.575 45.26-90.52 50.917H85.478C28.903 1012.685-5.042 961.768 0.616 905.193c28.287-243.27 113.15-418.652 260.243-537.458 107.492-84.862 231.956-130.122 367.735-141.437V118.807c0-50.917 22.63-96.177 67.89-113.15C736.086-5.657 781.345 0 815.29 33.945l362.077 367.735c28.288 22.63 45.26 56.574 50.918 96.176 5.657 39.603-5.658 79.205-33.945 107.492-5.658 5.658-11.315 16.972-22.63 22.63l-350.762 356.42c-22.63 22.63-50.918 33.945-79.205 33.945z m-90.52-339.448h90.52v226.298l356.42-367.734 5.658-5.658c5.657-5.657 5.657-16.972 5.657-22.63 0-11.315-5.657-16.972-11.315-22.63l-5.657-5.657-356.42-362.077V333.79l-79.205 5.658c-118.806 0-231.956 39.602-328.132 113.149-113.15 90.519-186.696 237.613-209.326 429.967 141.436-175.382 390.364-203.669 531.8-203.669z"/>
              </svg>
              <span class="count">{{ shareCount || 0 }}</span>
            </button>
          </div>
        </div>

        <!-- 评论区域 -->
        <ArticleComment 
          v-if="article.articleId"
          :article-id="String(article.articleId)"
          :article-author-id="String(article.authorId || article.userId)"
          :target-comment-id="String(route.query.commentId || '')"
        />
      </main>

      <!-- 右侧在线用户 -->
      <aside ref="onlineSidebarRef" :class="['online-sidebar', { 'ai-rail-reserved': showAiQuestion }]" :aria-hidden="showAiQuestion">
        <ReadingProgress :progress="readingProgress" :status="readingStatus" class="article-reading-progress" />
        <div class="online-header">
          <h3>在线观看</h3>
          <span class="online-count">{{ onlineUsers.length }}人</span>
        </div>
        <div class="online-users">
          <div 
            v-for="user in onlineUsers" 
            :key="user.userId"
            class="online-user-item"
            :title="user.nickName"
            @click="goToUserSpace(user.userId)"
          >
            <img 
              :src="getAvatarUrl(user.avatar)" 
              :alt="user.nickName"
              class="online-user-avatar"
              @error="handleAvatarError"
            >
            <span class="online-user-name">{{ user.nickName }}</span>
          </div>
          <div v-if="onlineUsers.length === 0" class="online-empty">
            暂无其他用户
          </div>
        </div>
        <button class="ask-article-ai-btn" @click="openAiQuestion" :disabled="!article.articleId || article.requiredLevel > 0" :title="article.requiredLevel > 0 ? '等级文章暂不支持 AI 问答' : ''">
          <span class="ask-ai-mark">✎</span> 问 AI <span class="ask-ai-arrow">↗</span>
        </button>
        <button class="open-chatroom-btn" @click="openChatroom">
          <svg viewBox="0 0 1024 1024" fill="currentColor" class="chat-icon">
            <path d="M535.552 796.444444H739.555556q70.712889 0 120.661333-50.005333Q910.222222 696.490667 910.222222 625.777778V341.333333q0-70.712889-50.005333-120.661333Q810.268444 170.666667 739.555556 170.666667H284.444444q-70.712889 0-120.661333 50.005333Q113.777778 270.620444 113.777778 341.333333v284.444445q0 70.712889 50.005333 120.661333Q213.731556 796.444444 284.444444 796.444444h13.084445q4.266667 8.533333 9.898667 16.497778 21.219556 30.151111 55.751111 44.487111 34.531556 14.279111 70.883555 7.964445 39.310222-6.826667 68.152889-35.612445L535.552 796.444444zM739.555556 682.666667H512a56.888889 56.888889 0 0 0-40.220444 16.668444l-50.005334 50.005333q-6.485333 6.485333-15.018666 2.958223Q398.222222 748.771556 398.222222 739.555556a56.888889 56.888889 0 0 0-56.888889-56.888889H284.444444q-23.552 0-40.220444-16.668445T227.555556 625.777778V341.333333q0-23.552 16.668444-40.220444T284.444444 284.444444h455.111112q23.552 0 40.220444 16.668445T796.444444 341.333333v284.444445q0 23.552-16.668444 40.220444T739.555556 682.666667zM341.333333 540.444444a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z"/>
          </svg>
          读者聊天室
          <span v-if="hasNewMessage" class="new-msg-dot"></span>
        </button>
      </aside>
      <Transition name="article-ai">
        <aside v-if="aiQuestionMounted" v-show="showAiQuestion" class="article-ai-drawer" :style="aiDrawerStyle" aria-label="文章问答">
          <AiChat :key="`${route.params.id}:${myUserId}`" embedded :origin-article-id="String(route.params.id)" :origin-article-title="article.title"
                  :reader-count="onlineUsers.length" :reader-unread="hasNewMessage"
                  @close="showAiQuestion = false" @open-chatroom="openChatroom" @login-required="handleAuthExpired" />
        </aside>
      </Transition>
    </div>

    <div v-if="showAiQuestion && !aiDocked" class="article-ai-backdrop" @click="showAiQuestion = false"></div>

    <!-- 移动端浮动按钮 -->
    <div v-show="!showAiQuestion" class="mobile-float-btn">
      <button class="float-btn mobile-ai-btn" aria-label="问 AI" @click="openAiQuestion">✎</button>
      <button class="float-btn" @click="openChatroom">
        <svg viewBox="0 0 1024 1024" fill="currentColor">
          <path d="M535.552 796.444444H739.555556q70.712889 0 120.661333-50.005333Q910.222222 696.490667 910.222222 625.777778V341.333333q0-70.712889-50.005333-120.661333Q810.268444 170.666667 739.555556 170.666667H284.444444q-70.712889 0-120.661333 50.005333Q113.777778 270.620444 113.777778 341.333333v284.444445q0 70.712889 50.005333 120.661333Q213.731556 796.444444 284.444444 796.444444h13.084445q4.266667 8.533333 9.898667 16.497778 21.219556 30.151111 55.751111 44.487111 34.531556 14.279111 70.883555 7.964445 39.310222-6.826667 68.152889-35.612445L535.552 796.444444zM739.555556 682.666667H512a56.888889 56.888889 0 0 0-40.220444 16.668444l-50.005334 50.005333q-6.485333 6.485333-15.018666 2.958223Q398.222222 748.771556 398.222222 739.555556a56.888889 56.888889 0 0 0-56.888889-56.888889H284.444444q-23.552 0-40.220444-16.668445T227.555556 625.777778V341.333333q0-23.552 16.668444-40.220444T284.444444 284.444444h455.111112q23.552 0 40.220444 16.668445T796.444444 341.333333v284.444445q0 23.552-16.668444 40.220444T739.555556 682.666667zM341.333333 540.444444a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z"/>
        </svg>
        <span v-if="hasNewMessage" class="float-new-dot"></span>
      </button>
      <span class="float-online-count">{{ onlineUsers.length }}人在线</span>
    </div>

    <!-- 聊天室弹窗 -->
    <div v-if="showChatroom" class="chatroom-overlay" @click="showChatroom = false">
      <div class="chatroom-modal" @click.stop>
        <div class="chatroom-header">
          <h3>文章聊天室</h3>
          <button class="close-btn" @click="showChatroom = false">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </button>
        </div>
        <div class="chatroom-notice">
          <svg viewBox="0 0 24 24" fill="currentColor" class="notice-icon">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
          </svg>
          消息不会保存，关闭文章页面后消息将被清除
        </div>
        <div class="chatroom-messages" ref="chatroomMessagesRef">
          <div 
            v-for="msg in chatroomMessages" 
            :key="msg.timestamp"
            :class="['chatroom-message', { self: msg.userId === myUserId }]"
          >
            <img 
              v-if="msg.userId !== myUserId"
              :src="getAvatarUrl(msg.avatar)" 
              class="chatroom-msg-avatar clickable"
              @click="goToUserSpace(msg.userId)"
              @error="handleAvatarError"
            >
            <div class="chatroom-msg-content">
              <div v-if="msg.userId !== myUserId" class="chatroom-msg-name clickable" @click="goToUserSpace(msg.userId)">{{ msg.nickName }}</div>
              <div class="chatroom-msg-bubble">{{ msg.content }}</div>
            </div>
          </div>
        </div>
        <div class="chatroom-input">
          <input 
            v-model="chatroomInput"
            type="text" 
            placeholder="输入消息..."
            @keydown.enter="sendChatroomMessage"
          >
          <button class="chatroom-send-btn" @click="sendChatroomMessage" :disabled="!chatroomInput.trim()">
            发送
          </button>
        </div>
      </div>
    </div>
    <!-- 图片预览弹窗 -->
    <div v-if="previewImage" class="image-preview-modal" @click="previewImage = ''">
      <img :src="previewImage" @click.stop />
      <span class="preview-close-btn" @click="previewImage = ''">×</span>
    </div>

    <!-- 登录弹窗 -->
    <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>

    <!-- 注册弹窗 -->
    <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
      <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { trackEffectiveReading } from '@/utils/effectiveReading'
import ReadingProgress from '@/components/ReadingProgress.vue'
import { ReadingHeartbeatPump, readingDuration, type ReadingProgress as Progress } from '@/utils/readingGrowth'
import { ref, onMounted, onUnmounted, nextTick, computed, watch, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { goBackOr, goBackUnless } from '../utils/navigation'
import ArticleComment from '../components/ArticleComment.vue'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { ensureAccessToken } from '../utils/authSession'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'
// 只用 highlight.js 打 token 标记；配色在 styles/theme.css 中与编辑器共用
import hljs from '@/utils/highlight'
import { safeHtml } from '@/utils/safeHtml'

const AiChat = defineAsyncComponent(() => import('./AiChat.vue'))

const route = useRoute()
const router = useRouter()

const article = ref<any>({
  title: '',
  content: '',
  authorName: '',
  authorAvatar: '',
  authorId: '',
  publishTime: '',
  viewCount: 0,
  likeCount: 0,
  collectCount: 0,
  coinCount: 0,
  hasLiked: false,
  hasCollected: false,
  summary: '',
  coverImage: '',
  isOriginal: false
})

const tocItems = ref<any[]>([])
const activeHeading = ref('')
const tocRef = ref<HTMLElement>()
// 鼠标停在目录上时用户可能在手动浏览目录，不自动滚动以免和用户抢位置
const tocHovered = ref(false)
// 当前项距目录可视区上下边缘至少保留这么多空间，否则把它滚到可视区上部三分之一处
const TOC_EDGE_MARGIN = 48

// 阅读正文时目录跟随：当前标题对应的目录项始终保持在目录可视区内。
// 只滚动目录容器自身，不使用 scrollIntoView，避免连带滚动整页。
function keepActiveTocItemVisible() {
  const container = tocRef.value
  if (!container || tocHovered.value) return
  const item = container.querySelector<HTMLElement>('.toc-item.active')
  if (!item) return
  const containerRect = container.getBoundingClientRect()
  const itemRect = item.getBoundingClientRect()
  const itemTop = itemRect.top - containerRect.top + container.scrollTop
  const visibleTop = container.scrollTop + TOC_EDGE_MARGIN
  const visibleBottom = container.scrollTop + container.clientHeight - TOC_EDGE_MARGIN
  if (itemTop >= visibleTop && itemTop + itemRect.height <= visibleBottom) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  container.scrollTo({
    top: Math.max(0, itemTop - container.clientHeight / 3),
    behavior: reduceMotion ? 'auto' : 'smooth',
  })
}

watch(activeHeading, () => nextTick(keepActiveTocItemVisible))
const contentRef = ref<HTMLElement>()

// 图片预览
const previewImage = ref('')

// 在线用户和聊天室
const onlineUsers = ref<any[]>([])
const showChatroom = ref(false)
const showAiQuestion = ref(false)
const aiQuestionMounted = ref(false)
const onlineSidebarRef = ref<HTMLElement>()
const aiDocked = ref(false)
const aiDockLeft = ref(0)
let aiLayoutObserver: ResizeObserver | undefined
const aiDrawerStyle = computed(() => aiDocked.value
  ? { left: `${aiDockLeft.value}px`, right: '20px', width: 'auto' }
  : {})

function updateAiLayout() {
  const rail = onlineSidebarRef.value?.getBoundingClientRect()
  const available = rail ? document.documentElement.clientWidth - rail.left - 20 : 0
  // Anchor to the original reader rail; reserve its layout space so neither
  // the reading column nor outline changes position when opening the panel.
  aiDocked.value = !!rail && rail.width > 0 && available >= 360
  aiDockLeft.value = rail?.left ?? 0
}

watch(showAiQuestion, () => nextTick(updateAiLayout))

function openAiQuestion() {
  if (article.value.requiredLevel > 0) return
  if (!localStorage.getItem('token')) { showLoginDialog.value = true; return }
  aiQuestionMounted.value = true
  showAiQuestion.value = true
}
const chatroomMessages = ref<any[]>([])
const chatroomInput = ref('')
const chatroomMessagesRef = ref<HTMLElement>()
const myUserId = ref(localStorage.getItem('userId') || '')
const hasNewMessage = ref(false)  // 新消息提示
const myNickName = ref(localStorage.getItem('nickName') || '')
const myAvatar = ref(localStorage.getItem('avatar') || '')

// WebSocket
let articleWs: WebSocket | null = null
let shouldReconnect = true
let heartbeatTimer: number | null = null
// 组件挂载时保存articleId，避免onUnmounted时route.params.id已变化
const currentArticleId = route.params.id as string
let detailDisposed = false

// 判断是否是作者
const isAuthor = computed(() => {
  const userId = localStorage.getItem('userId')
  return userId && (article.value.authorId === userId || article.value.userId === userId)
})
const readingProgress = ref<Progress>()
const readingStatus = ref('')
const selectedReadingLevel = ref(0)
const savingReadingLevel = ref(false)
const readingLevelFeedback = ref('')
let stopGrowth: (() => void) | undefined
async function saveReadingLevel() {
  savingReadingLevel.value = true; readingLevelFeedback.value = ''
  try {
    await request.put(`/article/${article.value.articleId}/reading-level`, { level: selectedReadingLevel.value })
    readingLevelFeedback.value = '已保存'; await fetchArticle()
  } catch (error) { readingLevelFeedback.value = error instanceof Error ? error.message : '保存失败' }
  finally { savingReadingLevel.value = false }
}
async function startGrowth(articleId: string) {
  if (!localStorage.getItem('token') || isAuthor.value || article.value.canReadFull === false) return
  let disposed = false
  let lastActivity = Date.now()
  const isActive = () => !document.hidden && document.hasFocus() && Date.now() - lastActivity < 120000
  const activity = () => { lastActivity = Date.now() }
  const events = ['pointerdown', 'pointermove', 'keydown', 'scroll', 'touchstart']
  for (const event of events) window.addEventListener(event, activity, { passive: true })
  let pump: ReadingHeartbeatPump | undefined
  let timer: ReturnType<typeof setInterval> | undefined
  const check = () => { if (!disposed) { const active = isActive(); readingStatus.value = active ? '正在累计有效阅读' : '计时暂停 · 页面在后台或暂时没有操作'; void pump?.update(active, Date.now()) } }
  const stop = () => {
    if (!disposed) void pump?.update(false, Date.now())
    disposed = true; pump?.stop(); clearInterval(timer)
    for (const event of events) window.removeEventListener(event, activity)
    document.removeEventListener('visibilitychange', check); window.removeEventListener('focus', check); window.removeEventListener('blur', check)
  }
  stopGrowth = stop
  try {
    const activeAtStart = isActive()
    const res = await request.post('/reading/sessions', { articleId, active: activeAtStart })
    if (disposed || detailDisposed) { stop(); return }
    readingProgress.value = res.data
    pump = new ReadingHeartbeatPump(res.data.sessionId, activeAtStart, Date.now(), async beat => {
      const result = await request.post('/reading/heartbeat', beat); return result.data
    }, progress => { readingProgress.value = progress }, error => {
      const message = error instanceof Error ? error.message : '网络暂不可用'
      readingStatus.value = message
      const terminal = /其他页面|等级|不存在|登录|账号/.test(message)
      if (terminal) stop()
      return terminal
    })
    timer = setInterval(check, 5000)
    document.addEventListener('visibilitychange', check); window.addEventListener('focus', check); window.addEventListener('blur', check)
    check()
  } catch (error) { stop(); readingStatus.value = error instanceof Error ? error.message : '阅读计时暂不可用' }
}

// 获取文章详情
async function fetchArticle() {
  try {
    const articleId = route.params.id
    console.log('获取文章详情:', articleId)
    
    const res = await request.get(`/article/detail/${articleId}`)
    if (detailDisposed || String(route.params.id) !== String(articleId)) return
    console.log('文章详情响应:', res)
    
    if (res.code === 200 && res.data) {
      // 确保 hasLiked 和 hasCollected 有默认值
      article.value = {
        ...res.data,
        authorId: res.data.authorId || res.data.userId,
        hasLiked: res.data.hasLiked || false,
        hasCollected: res.data.hasCollected || false
      }
      // 初始化分享数
      shareCount.value = res.data.shareCount || 0
      readingProgress.value = localStorage.getItem('token') ? res.data.readingProgress : undefined
      selectedReadingLevel.value = res.data.requiredLevel || 0
      stopGrowth?.()
      console.log('文章数据:', article.value)
      console.log('点赞状态:', article.value.hasLiked, '收藏状态:', article.value.hasCollected, '分享数:', shareCount.value)
      
      // 等待DOM更新后生成目录和代码高亮
      await nextTick()
      if (detailDisposed || String(route.params.id) !== String(articleId)) return
      generateTOC()
      highlightCode()
      bindImagePreview()  // 绑定图片点击预览
      stopReading?.()
      if (article.value.canReadFull !== false) {
        stopReading = trackEffectiveReading(() => increaseViewCount(String(articleId)))
        void startGrowth(String(articleId))
      }
    } else {
      alert(res.message || '获取文章失败')
    }
  } catch (error) {
    console.error('获取文章详情失败:', error)
    alert('获取文章失败')
  }
}

// 生成目录
function generateTOC() {
  tocItems.value = []
  if (!contentRef.value) return
  
  const headings = contentRef.value.querySelectorAll('h1, h2, h3, h4, h5, h6')
  const items: any[] = []
  
  headings.forEach((heading, index) => {
    const level = parseInt(heading.tagName.substring(1))
    const text = heading.textContent || ''
    const id = `heading-${index}`
    
    // 给标题添加ID
    heading.id = id
    
    items.push({ level, text, id })
  })
  
  tocItems.value = items
  console.log('生成目录:', items)
}

// 代码高亮
function highlightCode() {
  if (!contentRef.value) return
  
  const codeBlocks = contentRef.value.querySelectorAll('pre code')
  codeBlocks.forEach((block) => {
    hljs.highlightElement(block as HTMLElement)
  })
  console.log('代码高亮完成，共', codeBlocks.length, '个代码块')
}

// 绑定文章内容图片点击预览
function bindImagePreview() {
  if (!contentRef.value) return
  
  const images = contentRef.value.querySelectorAll('img')
  images.forEach((img) => {
    img.style.cursor = 'zoom-in'
    img.addEventListener('click', () => {
      previewImage.value = (img as HTMLImageElement).src
    })
  })
  console.log('图片预览绑定完成，共', images.length, '张图片')
}

// 标题与固定导航栏之间保留的间距
const HEADING_GAP = 16
// 点击目录后，等待平滑滚动结束再恢复滚动高亮
const SCROLL_SETTLE_MS = 150
let pendingHeading = ''
let settleTimer: ReturnType<typeof setTimeout> | undefined

// 导航栏高度随断点变化，按实际渲染位置计算偏移
function getHeadingOffset(): number {
  const navbar = document.querySelector<HTMLElement>('.article-detail-page .navbar')
  return (navbar?.getBoundingClientRect().bottom ?? 0) + HEADING_GAP
}

// 滚动到标题：一次性计算目标位置，避免两段平滑滚动互相打断
function scrollToHeading(id: string) {
  const element = document.getElementById(id)
  if (!element) return
  const top = element.getBoundingClientRect().top + window.scrollY - getHeadingOffset()
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  pendingHeading = id
  activeHeading.value = id
  window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion ? 'auto' : 'smooth' })
  scheduleSettle()
}

function scheduleSettle() {
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => { pendingHeading = '' }, SCROLL_SETTLE_MS)
}

// 点赞
async function toggleLike() {
  if (!checkLogin()) return
  
  try {
    const articleId = article.value.articleId || route.params.id
    const res = await request.post(`/action/article/${articleId}/like`)
    
    if (res.code === 200) {
      article.value.hasLiked = !article.value.hasLiked
      article.value.likeCount += article.value.hasLiked ? 1 : -1
    } else {
      alert(res.message || '操作失败')
    }
  } catch (error) {
    console.error('点赞失败:', error)
  }
}

// 收藏
async function toggleCollect() {
  if (!checkLogin()) return
  
  try {
    const articleId = article.value.articleId || route.params.id
    const res = await request.post(`/action/article/${articleId}/collect`)
    
    if (res.code === 200) {
      article.value.hasCollected = !article.value.hasCollected
      article.value.collectCount += article.value.hasCollected ? 1 : -1
    } else {
      alert(res.message || '操作失败')
    }
  } catch (error) {
    console.error('收藏失败:', error)
  }
}

// 投币（暂无后端接口，留作占位）
async function toggleCoin() {
  alert('投币功能开发中~')
}

// 分享文章
const shareCount = ref(0)

async function shareArticle() {
  if (!checkLogin()) return
  
  const url = window.location.href
  const title = article.value.title || '查看这篇文章'
  
  // 先复制链接到剪贴板
  let copySuccess = false
  try {
    await navigator.clipboard.writeText(url)
    copySuccess = true
  } catch (error) {
    // 备用方案：创建临时input
    try {
      const input = document.createElement('input')
      input.value = url
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
      copySuccess = true
    } catch (e) {
      console.error('复制失败:', e)
    }
  }
  
  // 调用后端接口记录分享（无论复制是否成功都调用）
  try {
    const articleId = article.value.articleId || route.params.id
    const res = await request.post('/share/record', {
      articleId: articleId,
      shareType: 0  // 0-复制链接
    })
    
    if (res.code === 200) {
      shareCount.value = res.data || 0
    }
  } catch (error) {
    console.error('记录分享失败:', error)
  }
  
  // 显示成功提示
  if (copySuccess) {
    showShareSuccess()
  }
}

function showShareSuccess() {
  // 创建提示框
  const toast = document.createElement('div')
  toast.className = 'share-toast'
  toast.innerHTML = `
    <svg viewBox="0 0 24 24" width="20" height="20" style="fill: var(--ej-accent)">
      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
    </svg>
    <span>链接已复制到剪贴板</span>
  `
  document.body.appendChild(toast)
  
  // 3秒后移除
  setTimeout(() => {
    toast.classList.add('fade-out')
    setTimeout(() => {
      document.body.removeChild(toast)
    }, 300)
  }, 3000)
}

// 编辑文章
function editArticle() {
  router.push(`/edit-article?id=${article.value.articleId || route.params.id}`)
}

// 判断路径是否为指定文章的详情页或编辑页（精确比较 ID，避免 12 误匹配 123）
function isPageOfArticle(path: string, articleId: string): boolean {
  const url = new URL(path, window.location.origin)
  return url.pathname === `/article/${articleId}`
    || (url.pathname === '/edit-article' && url.searchParams.get('id') === articleId)
}

// 删除文章
async function deleteArticle() {
  if (!confirm('确定要删除这篇文章吗？')) return
  
  const articleId = String(article.value.articleId || route.params.id)
  try {
    const res = await request.delete(`/article/${articleId}`)
    if (res.code === 200) {
      alert('删除成功')
      // 回到进入文章前的页面（个人空间、搜索结果、首页等）；
      // 上一页是这篇文章的详情或编辑页时已失效，改回作者自己的个人空间
      goBackUnless(router, previous => isPageOfArticle(previous, articleId), '/user-space')
    } else {
      alert(res.message || '删除失败')
    }
  } catch (error) {
    console.error('删除失败:', error)
    alert('删除失败')
  }
}

// 跳转到用户空间（新标签页打开）
function goToUserSpace(userId: string) {
  window.open(`/user-space/${userId}`, '_blank')
}

// 登录弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const dialogWidth = ref(window.innerWidth <= 480 ? '92%' : '420px')

// 检查登录（未登录弹出登录弹窗）
function checkLogin(): boolean {
  const token = localStorage.getItem('token')
  if (!token) {
    showLoginDialog.value = true
    return false
  }
  return true
}

// 登录成功处理
function handleLoginSuccess() {
  showLoginDialog.value = false
  myUserId.value = localStorage.getItem('userId') || ''
  myNickName.value = localStorage.getItem('nickName') || ''
  myAvatar.value = localStorage.getItem('avatar') || ''
  // 重新获取文章详情（刷新点赞/收藏状态）
  fetchArticle()
  // 重新连接 WebSocket
  initArticleWebSocket()
}

// 注册成功处理
function handleRegisterSuccess() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

// 切换到注册
function switchToRegister() {
  showLoginDialog.value = false
  showRegisterDialog.value = true
}

// 切换到登录
function switchToLogin() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

// 初始化文章 WebSocket
async function initArticleWebSocket() {
  let token: string | null
  try { token = await ensureAccessToken() } catch { return }
  if (!token) return
  if (articleWs && (articleWs.readyState === WebSocket.OPEN || articleWs.readyState === WebSocket.CONNECTING)) return
  
  shouldReconnect = true
  
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsHost = window.location.host
  articleWs = new WebSocket(`${wsProtocol}//${wsHost}/ws/article?token=${token}`)
  
  articleWs.onopen = () => {
    console.log('文章 WebSocket 连接成功')
    startHeartbeat()
    // 发送进入文章事件
    articleWs?.send(JSON.stringify({
      type: 'join_article',
      articleId: currentArticleId
    }))
  }
  
  articleWs.onmessage = (event) => {
    const data = JSON.parse(event.data)
    handleArticleWsMessage(data)
  }
  
  articleWs.onclose = () => {
    console.log('文章 WebSocket 连接关闭')
    stopHeartbeat()
    if (shouldReconnect) {
      setTimeout(() => {
        initArticleWebSocket()
      }, 3000)
    }
  }
  
  articleWs.onerror = (error) => {
    console.error('文章 WebSocket 错误:', error)
  }
}

// 处理 WebSocket 消息
function handleArticleWsMessage(data: any) {
  if (data.type === 'article_users_update') {
    // 更新在线用户列表
    onlineUsers.value = data.users || []
  } else if (data.type === 'article_chat_message') {
    // 接收聊天室消息
    chatroomMessages.value.push(data)
    scrollChatroomToBottom()
    // 如果聊天室关闭，显示新消息提示
    if (!showChatroom.value) {
      hasNewMessage.value = true
    }
  }
}

// 打开聊天室
function openChatroom() {
  showChatroom.value = true
  hasNewMessage.value = false  // 清除新消息提示
  scrollChatroomToBottom()
}

// 发送聊天室消息
function sendChatroomMessage() {
  const content = chatroomInput.value.trim()
  if (!content || !articleWs) return
  
  const message = {
    type: 'article_chat_message',
    articleId: currentArticleId,
    content: content
  }
  
  articleWs.send(JSON.stringify(message))
  chatroomInput.value = ''
  // 消息由后端广播统一返回，不需要手动添加
}

// 滚动聊天室到底部
function scrollChatroomToBottom() {
  nextTick(() => {
    if (chatroomMessagesRef.value) {
      chatroomMessagesRef.value.scrollTop = chatroomMessagesRef.value.scrollHeight
    }
  })
}

// 离开文章
function leaveArticle() {
  stopHeartbeat()
  if (articleWs && articleWs.readyState === WebSocket.OPEN) {
    articleWs.send(JSON.stringify({
      type: 'leave_article',
      articleId: currentArticleId
    }))
    shouldReconnect = false
    articleWs.close()
    articleWs = null
  }
}

// 心跳
function startHeartbeat() {
  heartbeatTimer = window.setInterval(() => {
    if (articleWs && articleWs.readyState === WebSocket.OPEN) {
      articleWs.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

// 格式化日期
function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 获取图片URL
function getImageUrl(url: string | undefined): string {
  if (!url) return '/images/default-cover.jpg'
  if (url.startsWith('http://') || url.startsWith('https://')) {
    if (url.includes('localhost:8080')) {
      return url.replace(/https?:\/\/localhost:8080/, '')
    }
    return url
  }
  if (url.startsWith('/uploads')) return url
  return url
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

// 头像加载失败
function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
}

// 封面加载失败
function handleCoverError(e: Event) {
  const target = e.target as HTMLImageElement
  target.src = '/images/default-cover.jpg'
}

// 增加浏览数（浏览15秒后调用）
async function increaseViewCount(articleId: string) {
  try {
    const response = await request.post(`/article/${articleId}/view`)
    if (String(route.params.id) === articleId && Number.isFinite(response.data?.viewCount)) article.value.viewCount = response.data.viewCount
  } catch (error) {
    console.error('增加浏览数失败:', error)
  }
}

// 浏览计时器
let stopReading: (() => void) | undefined

// 监听滚动更新目录激活项
function handleScroll() {
  // 点击目录触发的滚动过程中保持点击项高亮，
  // 否则文末标题因无法滚到顶部而永远不会被选中
  if (pendingHeading) {
    scheduleSettle()
    return
  }
  const headings = document.querySelectorAll('[id^="heading-"]')
  // 与跳转偏移使用同一基准，跳转后的标题即为当前高亮项
  const threshold = getHeadingOffset() + 1
  let currentActive = ''
  
  headings.forEach((heading) => {
    const rect = heading.getBoundingClientRect()
    if (rect.top <= threshold) {
      currentActive = heading.id
    }
  })
  
  activeHeading.value = currentActive
}

// 登录过期处理
function handleAuthExpired() {
  showAiQuestion.value = false
  aiQuestionMounted.value = false
  showLoginDialog.value = true
}

onMounted(() => {
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  fetchArticle()
  window.addEventListener('scroll', handleScroll)
  window.addEventListener('resize', updateAiLayout)
  updateAiLayout()
  aiLayoutObserver = new ResizeObserver(updateAiLayout)
  if (onlineSidebarRef.value?.parentElement) aiLayoutObserver.observe(onlineSidebarRef.value.parentElement)
  
  
  // 初始化文章 WebSocket
  initArticleWebSocket()
})

// 清理事件监听
onUnmounted(() => {
  detailDisposed = true
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  window.removeEventListener('scroll', handleScroll)
  window.removeEventListener('resize', updateAiLayout)
  aiLayoutObserver?.disconnect()
  clearTimeout(settleTimer)
  // 清理计时器
  stopReading?.()
  stopGrowth?.()
  // 离开文章
  leaveArticle()
})
</script>

<style scoped>
.article-detail-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
  /* clip 只裁剪横向溢出，不会像 hidden 那样形成滚动容器；否则左侧目录和右侧在线栏的 sticky 会失效 */
  overflow-x: clip;
}

.article-detail-page::before {
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
  transform: translateZ(0);
  backface-visibility: hidden;
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

.nav-right {
  display: flex;
  gap: 15px;
  align-items: center;
}

.nav-btn {
  background: transparent;
  color: #666;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
  transform: translateY(-2px);
}

.nav-btn.primary {
  background: var(--ej-accent);
  color: white;
}

.nav-btn.danger {
  background: #ff4d4f;
  color: white;
}

/* 主容器 */
.main-container {
  position: relative;
  z-index: 1;
  max-width: 1400px;
  margin: 100px auto 50px;
  padding: 0 20px;
  display: flex;
  gap: 30px;
  align-items: flex-start;
}

/* 左侧目录 */
.toc-sidebar {
  position: sticky;
  top: 100px;
  width: 280px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 15px;
  padding: 20px;
  max-height: calc(100vh - 150px);
  overflow-y: auto;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.toc-title {
  font-size: 16px;
  font-weight: 600;
  color: #1a1a1a;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 2px solid #f0f0f0;
}

.toc-list {
  list-style: none;
}

.toc-item {
  margin: 8px 0;
  cursor: pointer;
  transition: all 0.3s;
}

.toc-item a {
  display: block;
  color: #666;
  text-decoration: none;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 14px;
  line-height: 1.5;
  transition: all 0.3s;
  border-left: 3px solid transparent;
}

.toc-item a:hover {
  background: rgba(17, 17, 15, 0.1);
  color: var(--ej-accent);
  border-left-color: var(--ej-accent);
  transform: translateX(5px);
}

.toc-item.active a {
  background: rgba(17, 17, 15, 0.15);
  color: var(--ej-accent);
  border-left-color: var(--ej-accent);
  font-weight: 600;
}

.toc-item.level-1 { padding-left: 0; }
.toc-item.level-2 { padding-left: 15px; font-size: 13px; }
.toc-item.level-3 { padding-left: 30px; font-size: 12px; }
.toc-item.level-4 { padding-left: 45px; font-size: 12px; }
.toc-item.level-5 { padding-left: 60px; font-size: 12px; }

.toc-empty {
  color: #999;
  font-size: 14px;
  text-align: center;
  padding: 20px 10px;
}

/* 主内容 */
.main-content {
  flex: 1;
  min-width: 0;
}

/* 文章卡片 */
.article-card {
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 20px;
  padding: 40px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
}

/* 文章头部 */
.article-header {
  margin-bottom: 30px;
  border-bottom: 2px solid #f0f0f0;
  padding-bottom: 25px;
}

.article-title {
  font-size: 32px;
  color: #1a1a1a;
  font-weight: 600;
  margin-bottom: 20px;
  line-height: 1.4;
}

/* 文章标签区域 */
.article-tags-section {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
}

.category-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  background: linear-gradient(135deg, var(--ej-accent) 0%, #53664b 100%);
  color: white;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 16px;
  background: rgba(17, 17, 15, 0.1);
  color: var(--ej-accent);
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}

.tag-badge:hover {
  background: rgba(17, 17, 15, 0.2);
  transform: translateY(-2px);
}

.article-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  color: #666;
  font-size: 14px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.author-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid rgba(17, 17, 15, 0.3);
  cursor: pointer;
  object-fit: cover;
}

.author-name {
  color: var(--ej-accent);
  cursor: pointer;
  font-weight: 500;
}

.author-name:hover {
  text-decoration: underline;
}

.original-badge {
  background: linear-gradient(135deg, #ff6b6b, #feca57);
  color: white;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

/* 封面图 */
.article-cover {
  width: 100%;
  max-height: 400px;
  object-fit: cover;
  border-radius: 15px;
  margin-bottom: 30px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  cursor: zoom-in;
  transition: transform 0.2s, box-shadow 0.2s;
}

.article-cover:hover {
  transform: scale(1.01);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

/* 文章摘要 */
.article-summary {
  color: #666;
  font-size: 16px;
  line-height: 1.8;
  margin-bottom: 30px;
  padding: 20px;
  background: #f7f9fc;
  border-left: 4px solid var(--ej-accent);
  border-radius: 5px;
}

/* 文章内容 */
.article-content {
  color: #333;
  font-size: 16px;
  line-height: 2;
  word-wrap: break-word;
}

/* 正文各级标题的样式统一在 styles/theme.css 中定义，与编辑器共用 */

.article-content :deep(p) {
  margin-bottom: 16px;
  text-align: justify;
}

.article-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 10px;
  margin: 20px auto;
  display: block;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

/* 代码块与行内代码的样式统一在 styles/theme.css 中定义，与编辑器共用 */

.article-content :deep(ul),
.article-content :deep(ol) {
  margin: 15px 0 15px 30px;
  padding-left: 20px;
}

.article-content :deep(li) {
  margin-bottom: 10px;
  line-height: 1.8;
}

/* 互动区域 - B站风格 */
.action-bar {
  padding: 16px 0;
  margin-bottom: 20px;
  border-bottom: 1px solid #e5e7eb;
}

.action-btn-group {
  display: flex;
  gap: 28px;
  align-items: center;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  transition: color 0.2s;
  white-space: nowrap;
}

.action-btn:hover {
  color: var(--ej-accent);
}

/* 点赞 */
.action-btn.like-btn:hover {
  color: #ff6b8a;
}
.action-btn.like-btn.active {
  color: #ff6b8a;
}

/* 收藏 */
.action-btn.collect-btn:hover {
  color: #ffd700;
}
.action-btn.collect-btn.active {
  color: #ffd700;
}

/* 投币 */
.action-btn.coin-btn:hover {
  color: #daa520;
}

/* 分享 */
.action-btn.share-btn:hover {
  color: var(--ej-accent);
}

.action-btn.active .action-icon {
  animation: heartbeat 0.6s ease-in-out;
}

@keyframes heartbeat {
  0%, 100% { transform: scale(1); }
  25% { transform: scale(1.2); }
  50% { transform: scale(0.95); }
  75% { transform: scale(1.1); }
}

.action-icon {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
}

.action-btn .count {
  font-weight: 500;
  color: inherit;
}

/* 移动端浮动按钮 */
.mobile-float-btn {
  display: none;
  position: fixed;
  bottom: 30px;
  right: 20px;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 999;
}

.float-btn {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--ej-accent);
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(17, 17, 15, 0.4);
  transition: all 0.3s;
  position: relative;
}

.float-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 16px rgba(17, 17, 15, 0.5);
}

.float-btn svg {
  width: 26px;
  height: 26px;
}

.float-new-dot {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 12px;
  height: 12px;
  background: #ff4d4f;
  border-radius: 50%;
  border: 2px solid white;
  animation: pulse 1.5s infinite;
}

.float-online-count {
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  white-space: nowrap;
}

/* 响应式 */
@media (max-width: 1200px) {
  .toc-sidebar {
    display: none;
  }
  
  .online-sidebar {
    display: none;
  }
  
  /* 显示浮动按钮 */
  .mobile-float-btn {
    display: flex;
  }
}

/* 平板适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 55px;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .nav-right {
    gap: 8px;
  }
  
  .nav-btn {
    padding: 6px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  
  .toc-sidebar {
    display: none !important;
  }
  
  .online-sidebar {
    display: none !important;
  }
  
  .mobile-float-btn {
    display: flex !important;
  }
  
  .main-container {
    margin: 70px auto 100px;
    padding: 0 12px;
    flex-direction: column;
  }
  
  .main-content {
    width: 100%;
    max-width: none;
  }
  
  .article-card {
    padding: 20px 15px;
    border-radius: 12px;
  }
  
  .article-title {
    font-size: 22px;
  }
  
  .article-meta {
    gap: 10px;
    font-size: 12px;
    flex-wrap: wrap;
  }
  
  .author-avatar {
    width: 30px;
    height: 30px;
  }
  
  .article-cover {
    border-radius: 10px;
    margin: 15px 0;
  }
  
  .article-summary {
    font-size: 14px;
    padding: 12px;
  }
  
  .action-btn-group {
    gap: 16px;
    flex-wrap: wrap;
  }
  
  .action-btn {
    padding: 6px 2px;
    font-size: 13px;
  }
  
  .chatroom-modal {
    width: 95%;
    height: 80vh;
    max-height: none;
    border-radius: 12px;
  }
}

/* 手机适配 */
@media (max-width: 480px) {
  .navbar {
    padding: 0 10px;
    height: 50px;
  }
  
  .logo {
    font-size: 16px;
    flex-shrink: 0;
  }
  
  .logo-icon {
    width: 28px;
    height: 28px;
  }
  
  .logo-text {
    display: none;
  }
  
  .nav-right {
    gap: 5px;
  }
  
  .nav-btn {
    padding: 5px 8px;
    font-size: 11px;
    border-radius: 12px;
    white-space: nowrap;
  }
  
  .toc-sidebar {
    display: none !important;
  }
  
  .online-sidebar {
    display: none !important;
  }
  
  .mobile-float-btn {
    display: flex !important;
    bottom: 20px;
    right: 12px;
  }
  
  .main-container {
    margin: 60px auto 90px;
    padding: 0 8px;
    flex-direction: column;
  }
  
  .main-content {
    width: 100%;
  }
  
  .article-card {
    padding: 15px 12px;
    border-radius: 10px;
  }
  
  .article-header {
    margin-bottom: 15px;
    padding-bottom: 12px;
  }
  
  .article-title {
    font-size: 18px;
    margin-bottom: 12px;
  }
  
  .article-meta {
    gap: 8px;
    font-size: 11px;
    flex-wrap: wrap;
  }
  
  .author-avatar {
    width: 26px;
    height: 26px;
  }
  
  .article-cover {
    border-radius: 10px;
    margin-bottom: 20px;
  }
  
  .article-summary {
    padding: 15px;
    font-size: 14px;
    margin-bottom: 20px;
  }
  
  .article-content {
    font-size: 15px;
    line-height: 1.8;
  }
  
  .action-btn-group {
    gap: 12px;
    flex-wrap: wrap;
  }
  
  .action-btn {
    padding: 4px 2px;
    font-size: 12px;
  }
  
  .action-icon {
    width: 22px;
    height: 22px;
  }
  
  /* 聊天室弹窗手机适配 */
  .chatroom-modal {
    width: 100%;
    height: 100%;
    max-height: none;
    border-radius: 0;
  }
  
  .chatroom-header {
    padding: 15px;
  }
  
  .chatroom-header h3 {
    font-size: 16px;
  }
  
  .chatroom-notice {
    padding: 8px 15px;
    font-size: 11px;
  }
  
  .chatroom-messages {
    padding: 15px;
  }
  
  .chatroom-msg-avatar {
    width: 32px;
    height: 32px;
  }
  
  .chatroom-msg-bubble {
    padding: 8px 12px;
    font-size: 13px;
  }
  
  .chatroom-input {
    padding: 12px 15px;
  }
  
  .chatroom-input input {
    padding: 10px 12px;
    font-size: 14px;
  }
  
  .chatroom-send-btn {
    padding: 10px 18px;
    font-size: 13px;
  }
  
  /* 浮动按钮手机位置 */
  .mobile-float-btn {
    bottom: 20px;
    right: 15px;
  }
  
  .float-btn {
    width: 50px;
    height: 50px;
  }
  
  .float-btn svg {
    width: 22px;
    height: 22px;
  }
  
  .float-online-count {
    font-size: 10px;
    padding: 2px 6px;
  }
}

/* 右侧在线用户侧边栏 */
.online-sidebar {
  width: 260px;
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  height: fit-content;
  max-height: calc(100vh - 140px);
  position: sticky;
  top: 90px;
  display: flex;
  flex-direction: column;
}

.online-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.online-header h3 {
  margin: 0;
  font-size: 16px;
  color: #333;
}

.online-count {
  background: var(--ej-accent);
  color: white;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.online-users {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 15px;
}

.online-user-item {
  display: flex;
  align-items: center;
  padding: 10px;
  border-radius: 8px;
  margin-bottom: 8px;
  transition: background 0.2s;
  cursor: pointer;
}

.online-user-item:hover {
  background: #f5f5f5;
}

.online-user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  margin-right: 10px;
  cursor: pointer;
}

.online-user-name {
  font-size: 14px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.online-user-name:hover {
  color: var(--ej-accent);
}

.online-empty {
  text-align: center;
  padding: 40px 0;
  color: #999;
  font-size: 13px;
}

.open-chatroom-btn {
  width: 100%;
  padding: 12px;
  background: var(--ej-accent);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background 0.3s;
  position: relative;
}

.open-chatroom-btn:hover {
  background: var(--ej-ink);
}

.chat-icon {
  width: 18px;
  height: 18px;
}

/* 新消息红点 */
.new-msg-dot {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  background: #ff4d4f;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.2);
    opacity: 0.7;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}

/* 聊天室弹窗 */
.chatroom-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.chatroom-modal {
  width: 90%;
  max-width: 600px;
  height: 70vh;
  max-height: 600px;
  background: white;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.chatroom-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #f0f0f0;
}

.chatroom-header h3 {
  margin: 0;
  font-size: 18px;
  color: #333;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  color: #666;
}

.close-btn:hover {
  background: #f0f0f0;
}

.close-btn svg {
  width: 20px;
  height: 20px;
}

/* 聊天室提示条 */
.chatroom-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: #fff7e6;
  border-bottom: 1px solid #ffe7ba;
  color: #d48806;
  font-size: 12px;
}

.notice-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.chatroom-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f8f9fa;
}

.chatroom-message {
  display: flex;
  align-items: flex-start;
  margin-bottom: 15px;
  gap: 10px;
}

.chatroom-message.self {
  flex-direction: row-reverse;
}

.chatroom-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}

.chatroom-msg-avatar.clickable {
  cursor: pointer;
  transition: transform 0.2s;
}

.chatroom-msg-avatar.clickable:hover {
  transform: scale(1.1);
}

.chatroom-msg-content {
  max-width: 70%;
}

.chatroom-msg-name {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.chatroom-msg-name.clickable {
  cursor: pointer;
}

.chatroom-msg-name.clickable:hover {
  color: var(--ej-accent);
}

.chatroom-msg-bubble {
  padding: 10px 15px;
  border-radius: 12px;
  background: white;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.chatroom-message.self .chatroom-msg-bubble {
  background: var(--ej-accent);
  color: white;
}

.chatroom-input {
  display: flex;
  gap: 10px;
  padding: 15px 20px;
  border-top: 1px solid #f0f0f0;
  background: white;
}

.chatroom-input input {
  flex: 1;
  padding: 10px 15px;
  border: 1px solid #e0e0e0;
  border-radius: 20px;
  outline: none;
  font-size: 14px;
}

.chatroom-input input:focus {
  border-color: var(--ej-accent);
}

.chatroom-send-btn {
  padding: 10px 24px;
  background: var(--ej-accent);
  color: white;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.3s;
}

.chatroom-send-btn:hover:not(:disabled) {
  background: var(--ej-ink);
}

.chatroom-send-btn:disabled {
  background: #c0c4cc;
  cursor: not-allowed;
}

/* 分享提示框 */
.share-toast {
  position: fixed;
  top: 100px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: white;
  border-radius: 50px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 9999;
  animation: slideDown 0.3s ease;
  font-size: 14px;
  color: #333;
  border: 1.5px solid var(--ej-ink);
}

.share-toast.fade-out {
  animation: fadeOut 0.3s ease forwards;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}

@keyframes fadeOut {
  to {
    opacity: 0;
    transform: translateX(-50%) translateY(-10px);
  }
}

/* 图片预览弹窗 */
.image-preview-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 99999;
  cursor: zoom-out;
  animation: fadeIn 0.2s ease;
}

.image-preview-modal img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
  cursor: default;
}

.preview-close-btn {
  position: absolute;
  top: 20px;
  right: 30px;
  width: 40px;
  height: 40px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border-radius: 50%;
  font-size: 28px;
  line-height: 40px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.preview-close-btn:hover {
  background: rgba(255, 255, 255, 0.4);
  transform: rotate(90deg);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 文章内容中的图片可点击 */
.article-content :deep(img) {
  cursor: zoom-in;
  transition: transform 0.2s;
}

.article-content :deep(img):hover {
  transform: scale(1.02);
}

/* 图片预览移动端适配 */
@media (max-width: 768px) {
  .image-preview-modal {
    background: rgba(0, 0, 0, 0.95);
  }
  
  .image-preview-modal img {
    max-width: 100vw;
    max-height: 85vh;
    border-radius: 0;
  }
  
  .preview-close-btn {
    top: 15px;
    right: 15px;
    width: 36px;
    height: 36px;
    font-size: 24px;
    line-height: 36px;
    background: rgba(255, 255, 255, 0.3);
  }
  
  /* 移动端取消悬停效果 */
  .article-content :deep(img):hover {
    transform: none;
  }
}
.ask-article-ai-btn { display: flex; align-items: center; justify-content: center; gap: 9px; width: 100%; margin-bottom: 10px; padding: 11px 14px; background: var(--ej-lime, #caff4d); border: 1px solid var(--ej-ink); border-radius: 999px; font-size: 14px; color: var(--ej-ink); cursor: pointer; transition: transform .18s ease, box-shadow .18s ease; }
.ask-article-ai-btn:hover { transform: translateY(-2px); box-shadow: 0 3px 0 #11110f1a; }
.ask-article-ai-btn:disabled { opacity: .5; cursor: default; }
.ask-ai-mark { font-size: 18px; }
.ask-ai-arrow { margin-left: auto; }
.article-ai-drawer { position: fixed; z-index: 2000; top: 96px; bottom: 20px; right: 20px; width: min(480px, calc(100% - 40px)); overflow: hidden; background: var(--ej-surface); border: 1.5px solid var(--ej-ink); border-radius: 20px; box-shadow: 0 5px 0 #11110f12; }
.article-ai-backdrop { position: fixed; inset: 72px 0 0; z-index: 1900; background: #11110f20; }
:global(#app .article-detail-page.ai-question-open .main-container) { z-index: auto; }
:global(#app .article-detail-page .online-sidebar.ai-rail-reserved) { visibility: hidden; pointer-events: none; }
.article-ai-enter-active, .article-ai-leave-active { transition: opacity .22s ease, transform .22s ease; }
.article-ai-enter-from, .article-ai-leave-to { opacity: 0; transform: translateX(14px); }
@media (max-width: 1050px) {
  .article-ai-drawer { position: fixed; z-index: 2000; top: 84px; bottom: 14px; right: 14px; width: min(480px, calc(100% - 28px)); height: auto; }
  .article-ai-backdrop { display: block; position: fixed; inset: 70px 0 0; z-index: 1900; background: #11110f20; }
}
@media (max-width: 480px) {
  .article-ai-drawer { top: 78px; right: 8px; bottom: 8px; width: calc(100% - 16px); border-radius: 18px; }
}
@media (prefers-reduced-motion: reduce) { .article-ai-enter-active, .article-ai-leave-active, .ask-article-ai-btn { transition: none; } }
</style>
