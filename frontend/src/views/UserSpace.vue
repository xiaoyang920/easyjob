<template>
  <div class="user-space-page">
    <StarBackground />
    
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
      
      <!-- 搜索框 -->
      <div class="search-box">
        <input 
          v-model="searchKeyword"
          type="search" 
          placeholder="搜索文章、作者..."
          @keyup.enter="handleSearch"
          @keydown.enter="handleSearch"
          @search="handleSearch"
          enterkeyhint="search"
        >
        <button class="search-btn" @click="handleSearch">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
          </svg>
        </button>
      </div>
      
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/')">首页</button>
        <template v-if="isOwner">
          <button class="nav-btn" @click="$router.push('/draft-box')">草稿箱</button>
          <button class="nav-btn primary" @click="$router.push('/create-article')">发布文章</button>
        </template>
        <button class="nav-btn logout" @click="logout">退出登录</button>
      </div>
    </nav>

    <!-- 用户信息头部 -->
    <div class="space-header">
      <div class="header-content">
        <img 
          :src="getAvatarUrl(userInfo.avatar)" 
          alt="用户头像" 
          class="user-avatar"
          @error="handleAvatarError"
        >
        <div class="user-info">
          <div class="username">
            <span>{{ userInfo.nickName || '加载中...' }}</span>
            <span v-if="userInfo.role === 2" class="user-badge admin">管理员</span>
            <span v-else class="user-badge">普通用户</span>
          </div>
          <div class="user-intro">{{ userInfo.personIntroduction || '这个人很懒，什么都没有留下~' }}</div>
          <div class="user-stats">
            <div class="stat-item" @click="goToFollowers">
              <span class="stat-value">{{ userInfo.followerCount || 0 }}</span>
              <span class="stat-label">粉丝</span>
            </div>
            <div class="stat-item" @click="goToFollowing">
              <span class="stat-value">{{ userInfo.followingCount || 0 }}</span>
              <span class="stat-label">关注</span>
            </div>
            <div class="stat-item">
              <span class="stat-value">{{ userInfo.articleCount || 0 }}</span>
              <span class="stat-label">文章</span>
            </div>
          </div>
        </div>
        <div class="header-actions">
          <template v-if="isOwner">
            <button class="action-btn" @click="openEditModal">编辑资料</button>
          </template>
          <template v-else>
            <button 
              :class="['action-btn', isFollowing ? '' : 'primary']" 
              @click="toggleFollow"
            >
              {{ isFollowing ? '已关注' : '关注' }}
            </button>
            <button class="action-btn chat-btn" @click="startChat">
              <svg width="16" height="16" viewBox="0 0 1024 1024" fill="currentColor">
                <path d="M535.552 796.444444H739.555556q70.712889 0 120.661333-50.005333Q910.222222 696.490667 910.222222 625.777778V341.333333q0-70.712889-50.005333-120.661333Q810.268444 170.666667 739.555556 170.666667H284.444444q-70.712889 0-120.661333 50.005333Q113.777778 270.620444 113.777778 341.333333v284.444445q0 70.712889 50.005333 120.661333Q213.731556 796.444444 284.444444 796.444444h13.084445q4.266667 8.533333 9.898667 16.497778 21.219556 30.151111 55.751111 44.487111 34.531556 14.279111 70.883555 7.964445 39.310222-6.826667 68.152889-35.612445L535.552 796.444444zM739.555556 682.666667H512a56.888889 56.888889 0 0 0-40.220444 16.668444l-50.005334 50.005333q-6.485333 6.485333-15.018666 2.958223Q398.222222 748.771556 398.222222 739.555556a56.888889 56.888889 0 0 0-56.888889-56.888889H284.444444q-23.552 0-40.220444-16.668445T227.555556 625.777778V341.333333q0-23.552 16.668444-40.220444T284.444444 284.444444h455.111112q23.552 0 40.220444 16.668445T796.444444 341.333333v284.444445q0 23.552-16.668444 40.220444T739.555556 682.666667zM341.333333 540.444444a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z m170.666667 0a56.888889 56.888889 0 1 0 0-113.777777 56.888889 56.888889 0 0 0 0 113.777777z"/>
              </svg>
              私聊
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- 主要内容 -->
    <div class="main-content">
      <!-- 左侧内容 -->
      <div class="content-left">
        <!-- 标签页 -->
        <div class="tabs">
          <div 
            :class="['tab-item', { active: currentTab === 'article' }]"
            @click="switchTab('article')"
          >
            <svg viewBox="0 0 24 24"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM6 20V4h7v5h5v11H6z"/></svg>
            文章
            <span class="tab-badge">{{ userInfo.articleCount || 0 }}</span>
          </div>
          <div 
            :class="['tab-item', { active: currentTab === 'collect' }]"
            @click="switchTab('collect')"
          >
            <svg viewBox="0 0 1059 1024"><path d="M253.488042 1024c-16.9 0-33.2875-5.1125-47.6125-15.3625-26.625-18.425-39.425-49.6625-34.3125-81.925l40.9625-251.9c1.5375-10.2375-1.5375-20.475-8.7-27.65L28.213042 466.4375c-22.0125-22.525-29.1875-55.3-19.45-84.9875 9.725-29.7 35.325-51.2 66.05-55.8125l237.575-36.35c10.75-1.5375 19.4625-8.1875 24.0625-17.925L441.388042 48.125c13.825-29.7 42.5-48.125 75.2625-48.125s61.4375 18.4375 75.2625 48.125l104.45 223.2375c4.6125 9.725 13.825 16.375 24.0625 17.925L958.000542 325.625a82.355 82.355 0 0 1 66.05 55.8125c10.2375 29.7 2.5625 62.4625-19.45 84.9875l-175.625 180.7375c-7.1625 7.175-10.2375 17.925-8.7 27.65l40.9625 251.9c5.125 31.75-8.1875 63.4875-34.3 81.925-26.1125 18.4375-59.9 20.4875-88.0625 4.6125l-206.85-114.6875c-9.725-5.1125-20.9875-5.1125-30.7125 0l-207.3625 115.2c-12.8125 6.65-26.6375 10.2375-40.4625 10.2375zM516.650542 51.2c-12.8 0-23.55 7.1625-29.1875 18.4375L383.525542 292.875c-11.775 25.0875-35.325 43.0125-62.975 47.1l-237.575 36.35c-12.2875 2.05-21.5 9.7375-25.6 21.5-4.1 11.775-1.025 24.0625 7.675 32.775L240.688042 611.325c18.4375 18.95 26.625 45.5625 22.525 71.675L222.250542 934.9125c-2.05 12.8 3.075 24.575 13.3125 31.7375 10.2375 7.175 23.0375 7.6875 33.7875 1.5375l207.3625-115.2c25.0875-13.825 55.3-13.825 80.3875 0l207.3625 115.2c10.75 6.1375 23.55 5.625 33.8-1.5375 10.2375-7.1625 15.3625-18.95 13.3125-31.7375L770.625542 683.0125c-4.1-26.1125 4.1-52.7375 22.525-71.675l175.625-180.7375c8.7-8.7 11.2625-20.9875 7.675-32.775-4.0875-11.775-13.3125-19.9625-25.6-21.5l-237.5625-36.35c-27.65-4.0875-51.2-22.0125-62.975-47.1L545.838042 69.6375c-5.625-11.2625-16.375-18.4375-29.1875-18.4375z m0 0" fill="currentColor"/></svg>
            收藏
          </div>
          <div 
            :class="['tab-item', { active: currentTab === 'like' }]"
            @click="switchTab('like')"
          >
            <svg viewBox="0 0 1024 1024">
              <path d="M939.358251 423.424662c-23.01825-37.252439-62.924121-60.779272-107.019409-63.209624-2.755764-0.38681-5.510504-0.579191-8.347109-0.579191l-152.202471-0.121773c6.649444-28.975938 10.015098-58.653865 10.015098-88.657202 0-28.223808-3.213181-57.139372-9.556657-85.952604-0.447185-2.043542-1.098008-4.006244-1.932002-5.866614-15.820314-57.302077-67.37755-96.841605-127.282918-96.841605-72.827679 0-132.081201 59.254545-132.081201 132.081201 0 3.334955 0.132006 6.66991 0.406253 10.015098-2.196015 57.211003-32.108279 109.947088-80.269162 141.363611-14.447037 9.42465-18.524912 28.773324-9.099239 43.220361 9.414417 14.437827 28.752858 18.535145 43.220361 9.099239 65.811892-42.925648 106.429984-115.325585 108.656699-193.684234 0.030699-1.332345-0.010233-2.663666-0.14224-3.996011-0.203638-2.012843-0.304945-4.016477-0.304945-6.019087 0-38.381146 31.233352-69.614497 69.614497-69.614497 32.57593 0 60.474326 22.204721 67.824735 53.997821 0.356111 1.534959 0.823761 3.019777 1.402953 4.453429 4.696975 22.814612 7.076162 45.579081 7.076162 67.743894 0 37.485753-6.222725 74.352405-18.494213 109.592001-3.324722 9.546424-1.819438 20.111037 4.02671 28.345582 5.856381 8.245801 15.332197 13.146415 25.448602 13.156648l193.226816 0.101307c1.423419 0.264013 2.857071 0.426719 4.300956 0.477884 24.116257 0.9967 45.935192 13.614066 58.603723 34.090423 7.838525 12.31242 11.438517 26.800389 10.431583 41.939181-0.080841 0.945535-0.121773 1.911536-0.11154 2.877537 0 0.854461 0.040932 1.697665 0.11154 2.53166 0.010233 0.335644-0.030699 0.661056-0.11154 0.976234-0.101307 0.376577-0.193405 0.772596-0.284479 1.159406l-74.972529 330.391802c-0.914836 1.281179-1.738597 2.6432-2.449795 4.046153-5.937223 11.762905-14.660908 21.48329-25.346271 28.172643-10.746762 6.812149-23.059182 10.614755-35.757388 11.06194-0.854461-0.061398-513.766226-0.224104-513.766226-0.224104-0.467651-0.020466-0.935302-0.030699-1.402953-0.030699 0 0-111.01542 0.172939-112.718201 0.457418-1.932002 0-3.446495-1.50426-3.446495-3.415796l0.299829-416.334173c0-1.901303 1.545192-3.446495 3.01466-3.456728l1.245364 0.121773c1.174756 0.132006 2.653433 0.284479 3.52836 0.193405l83.82822-0.222057 0 339.367221c0 17.253966 13.979386 31.233352 31.233352 31.233352s31.233352-13.979386 31.233352-31.233352L281.009092 435.350273c0-1.778506 0-8.631588 0-10.411117 0-17.253966-13.979386-30.928407-31.233352-30.928407-1.50426 0-117.547183 0.304945-119.402437 0.304945-36.34272 0-65.913199 29.566386-65.913199 65.893756l-0.299829 416.334173c0 36.337603 29.571503 65.902966 65.913199 65.902966 2.541893 0 111.406323-0.457418 111.406323-0.457418 0.457418 0.020466 0.925069 0.030699 1.382487 0.030699 0 0 511.458671 0.274246 512.505513 0.274246 25.469068 0 50.296523-7.197936 71.647807-20.73116 19.612687-12.281721 35.777855-29.881564 46.839795-50.967812 3.660366-5.622044 6.435573-11.875468 8.256034-18.615986 0.11154-0.416486 0.213871-0.823761 0.304945-1.240247l74.881454-330.340637c1.596358-6.212492 2.257413-12.586666 2.00261-18.992563C960.892707 473.366098 953.948551 446.331371 939.358251 423.424662z" fill="currentColor"/>
              <path d="M450.027553 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C481.260905 532.629853 467.281519 518.650467 450.027553 518.650467z" fill="currentColor"/>
              <path d="M693.805696 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C725.039048 532.629853 711.058638 518.650467 693.805696 518.650467z" fill="currentColor"/>
              <path d="M648.940882 660.09492c-14.304797-9.393951-33.592073-5.398964-43.159986 8.763594-0.132006 0.193405-13.614066 19.754926-34.171264 19.754926-19.98824 0-32.423457-18.09717-33.266661-19.368116-9.17087-14.427594-28.254507-18.809391-42.834574-9.770528-14.650675 9.109472-19.155269 28.366048-10.055007 43.016723 11.214413 18.047028 41.96988 48.588625 86.156242 48.588625 43.962258 0 75.104535-30.318516 86.572728-48.222281C667.404396 688.461991 663.216004 669.500127 648.940882 660.09492z" fill="currentColor"/>
            </svg>
            点赞
          </div>
        </div>

        <!-- 过滤器 -->
        <div class="filter-bar">
          <button 
            v-for="filter in filters" 
            :key="filter.value"
            :class="['filter-btn', { active: currentOrder === filter.value }]"
            @click="changeOrder(filter.value)"
          >
            {{ filter.label }}
          </button>
        </div>

        <!-- 文章列表 -->
        <div v-if="loading" class="loading-state">加载中...</div>
        <div v-else-if="articles.length === 0" class="empty-state">
          暂无内容
        </div>
        <div v-else class="article-grid">
          <div 
            v-for="article in articles" 
            :key="article.articleId"
            class="article-card"
            @click="viewArticle(article.articleId)"
          >
            <div class="cover-wrapper">
              <img 
                v-if="getImageUrl(article.coverImage)"
                v-lazyload="{
                  src: getThumbUrl(getImageUrl(article.coverImage)) || getImageUrl(article.coverImage),
                  fallback: getImageUrl(article.coverImage)
                }"
                :alt="article.title" 
                class="article-cover"
                @error="handleCoverError($event, article.coverImage)"
              >
              <div 
                v-else 
                class="no-cover-placeholder"
                :style="{ background: getGradientColor(article.articleId) }"
              >
                <span class="placeholder-title">{{ stripHtmlTags(article.title) }}</span>
              </div>
            </div>
            <div class="article-info">
              <div class="article-title">{{ article.title }}</div>
              <div class="article-meta">
                <span>{{ article.viewCount || 0 }} 观看</span>
                <span>{{ article.likeCount || 0 }} 点赞</span>
                <span>{{ article.collectCount || 0 }} 收藏</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="articles.length > 0" class="pagination">
          <button 
            class="page-btn" 
            :disabled="currentPage === 1"
            @click="changePage(currentPage - 1)"
          >
            上一页
          </button>
          <span class="page-info">{{ currentPage }} / {{ totalPages || 1 }}</span>
          <button 
            class="page-btn" 
            :disabled="currentPage >= totalPages"
            @click="changePage(currentPage + 1)"
          >
            下一页
          </button>
        </div>
      </div>

      <!-- 右侧边栏 -->
      <div class="content-right">
        <!-- 空间公告 -->
        <div class="sidebar-card">
          <div class="card-title">空间公告</div>
          <div class="notice-content">
            {{ userInfo.noticeInfo || '暂无公告' }}
          </div>
        </div>
        
        <!-- 硬币信息 -->
        <div v-if="isOwner" class="sidebar-card">
          <div class="card-title">硬币余额</div>
          <div class="coin-info">
            <div class="coin-item">
              <div class="coin-value">{{ userInfo.currentCoinCount || 0 }}</div>
              <div class="coin-label">当前硬币</div>
            </div>
            <div class="coin-item">
              <div class="coin-value">{{ userInfo.totalCoinCount || 0 }}</div>
              <div class="coin-label">累计获得</div>
            </div>
          </div>
        </div>
        
        <!-- 个人信息 -->
        <div class="sidebar-card">
          <div class="card-title">个人信息</div>
          <div class="user-detail-card">
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>
              </span>
              <span>{{ userInfo.email || '-' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V9h14v10zM7 11h5v5H7z"/></svg>
              </span>
              <span>{{ userInfo.birthday || '未设置' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
              </span>
              <span>{{ getSexText(userInfo.sex) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z"/></svg>
              </span>
              <span>{{ userInfo.school || '未填写' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M9 11H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2zm2-7h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V9h14v11z"/></svg>
              </span>
              <span>{{ formatDate(userInfo.joinTime) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-icon">
                <svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
              </span>
              <span>{{ formatDate(userInfo.lastLoginTime) }}</span>
            </div>
          </div>
        </div>

        <!-- 直播间 -->
        <div class="sidebar-card">
          <div class="card-title">直播间</div>
          <div class="live-status">
            <div class="live-tip">期待你的分享时刻~</div>
            <button class="live-btn">前往直播间 ➜</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑资料弹窗 -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content">
        <div class="modal-header">
          <h2>编辑资料</h2>
          <button class="modal-close" @click="closeEditModal">×</button>
        </div>
        <div class="modal-body">
          <!-- 头像 -->
          <div class="edit-avatar-section">
            <div class="edit-avatar-upload">
              <img v-if="!avatarUploading" :src="getAvatarUrl(editProfile.avatar)" alt="头像" class="edit-avatar-preview" @error="handleAvatarError">
              <div v-if="avatarUploading" class="edit-avatar-progress">
                <div class="progress-bar" :style="{ height: avatarProgress + '%' }"></div>
                <span class="progress-text">{{ avatarProgress }}%</span>
              </div>
              <div v-if="!avatarUploading" class="edit-avatar-overlay">
                <span>更换头像</span>
              </div>
              <input type="file" accept="image/*" @change="uploadAvatar" class="edit-file-input">
            </div>
          </div>
          
          <!-- 昵称 -->
          <div class="edit-form-item">
            <label>昵称 <span class="required">*</span></label>
            <input v-model="editProfile.nickName" type="text" placeholder="请输入昵称" maxlength="20">
          </div>
          
          <!-- 性别和生日 -->
          <div class="edit-form-row">
            <div class="edit-form-item">
              <label>性别</label>
              <select v-model="editProfile.sex">
                <option :value="2">未知</option>
                <option :value="1">男</option>
                <option :value="0">女</option>
              </select>
            </div>
            <div class="edit-form-item">
              <label>生日</label>
              <input v-model="editProfile.birthday" type="date">
            </div>
          </div>
          
          <!-- 学校 -->
          <div class="edit-form-item">
            <label>学校</label>
            <input v-model="editProfile.school" type="text" placeholder="请输入学校名称" maxlength="100">
          </div>
          
          <!-- 个人简介 -->
          <div class="edit-form-item">
            <label>个人简介</label>
            <textarea v-model="editProfile.personIntroduction" placeholder="介绍一下自己吧~" rows="2" maxlength="200"></textarea>
          </div>
          
          <!-- 空间公告 -->
          <div class="edit-form-item">
            <label>空间公告</label>
            <textarea v-model="editProfile.noticeInfo" placeholder="设置你的空间公告" rows="2" maxlength="200"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="modal-cancel" @click="closeEditModal">取消</button>
          <button class="modal-submit" @click="saveProfile" :disabled="saving">{{ saving ? '保存中...' : '保存' }}</button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StarBackground from '../components/StarBackground.vue'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { getThumbUrl } from '../utils/image'
import { uploadFile } from '../utils/upload'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'

const route = useRoute()
const router = useRouter()

const userInfo = ref<any>({})
const articles = ref<any[]>([])
const loading = ref(false)
const currentTab = ref('article')
const currentOrder = ref('latest')
const currentPage = ref(1)
const totalPages = ref(0)
const isFollowing = ref(false)
const initialized = ref(false)
const searchKeyword = ref('')

// 编辑资料弹窗
const showEditModal = ref(false)
const saving = ref(false)
const avatarUploading = ref(false)
const avatarProgress = ref(0)
const editProfile = ref({
  nickName: '',
  avatar: '',
  sex: 2,
  birthday: '',
  school: '',
  personIntroduction: '',
  noticeInfo: ''
})

// 生成基于文章ID的随机颜色
function getGradientColor(id: string | number): string {
  // 统一返回灰色背景
  return '#e8e8e8';
}

const filters = [
  { label: '最新发布', value: 'latest' },
  { label: '最多观看', value: 'hottest' },
  { label: '最多点赞', value: 'like' },
  { label: '最多收藏', value: 'collect' }
]

// 判断是否是自己的空间
const isOwner = computed(() => {
  const currentUserId = localStorage.getItem('userId')
  const viewingUserId = route.params.id || currentUserId
  return currentUserId && currentUserId === String(viewingUserId)
})

// 获取用户ID
const userId = computed(() => {
  const paramId = route.params.id
  // 过滤无效值
  if (paramId && paramId !== 'undefined' && paramId !== 'null') {
    return paramId
  }
  return localStorage.getItem('userId')
})

// 获取用户信息
async function fetchUserInfo() {
  try {
    const res = await request.get(`/user/space/${userId.value}`)
    console.log('用户信息:', res)
    if (res.code === 200 && res.data) {
      userInfo.value = res.data
    }
  } catch (error) {
    console.error('获取用户信息失败:', error)
  }
}

// 获取关注状态
async function fetchFollowStatus() {
  if (isOwner.value) return
  
  try {
    const res = await request.get(`/user/${userId.value}/follow-status`)
    if (res.code === 200 && res.data) {
      isFollowing.value = res.data.isFollowing
    }
  } catch (error) {
    console.error('获取关注状态失败:', error)
  }
}

// 获取文章列表
async function fetchArticles(reset = false) {
  if (reset) {
    currentPage.value = 1
  }
  
  // 首次加载才显示loading
  if (!initialized.value) {
    loading.value = true
  }
  
  try {
    let url = ''
    if (currentTab.value === 'article') {
      url = `/article/user/${userId.value}?page=${currentPage.value}&size=12&order=${currentOrder.value}`
    } else if (currentTab.value === 'collect') {
      url = `/action/user/${userId.value}/collect?page=${currentPage.value}&size=12&order=${currentOrder.value}`
    } else if (currentTab.value === 'like') {
      url = `/action/user/${userId.value}/like?page=${currentPage.value}&size=12&order=${currentOrder.value}`
    }
    
    const res = await request.get(url)
    console.log('文章列表:', res)
    
    if (res.code === 200 && res.data) {
      articles.value = res.data.records || []
      totalPages.value = res.data.pages || 0
    }
  } catch (error) {
    console.error('获取文章列表失败:', error)
  } finally {
    loading.value = false
    initialized.value = true
  }
}

// 切换标签
function switchTab(tab: string) {
  currentTab.value = tab
  currentOrder.value = 'latest'
  fetchArticles(true)
}

// 切换排序
function changeOrder(order: string) {
  currentOrder.value = order
  fetchArticles(true)
}

// 切换页码
function changePage(page: number) {
  currentPage.value = page
  fetchArticles()
  window.scrollTo({ top: 400, behavior: 'smooth' })
}

// 关注/取消关注
async function toggleFollow() {
  const token = localStorage.getItem('token')
  if (!token) {
    alert('请先登录')
    router.push('/login')
    return
  }
  
  try {
    const url = isFollowing.value 
      ? `/user/${userId.value}/unfollow`
      : `/user/${userId.value}/follow`
    
    const res = await request.post(url)
    if (res.code === 200) {
      isFollowing.value = !isFollowing.value
      // 更新粉丝数
      if (isFollowing.value) {
        userInfo.value.followerCount = (userInfo.value.followerCount || 0) + 1
      } else {
        userInfo.value.followerCount = Math.max(0, (userInfo.value.followerCount || 0) - 1)
      }
    } else {
      alert(res.message || '操作失败')
    }
  } catch (error) {
    console.error('关注操作失败:', error)
  }
}

// 查看文章
function viewArticle(articleId: string) {
  window.open(`/article/${articleId}`, '_blank')
}
function goToFollowers() {
  router.push(`/followers-following?userId=${userId.value}&tab=followers`)
}

// 跳转到关注页
function goToFollowing() {
  router.push(`/followers-following?userId=${userId.value}&tab=following`)
}

// 打开编辑资料弹窗
function openEditModal() {
  editProfile.value = {
    nickName: userInfo.value.nickName || '',
    avatar: userInfo.value.avatar || '',
    sex: userInfo.value.sex ?? 2,
    birthday: userInfo.value.birthday || '',
    school: userInfo.value.school || '',
    personIntroduction: userInfo.value.personIntroduction || '',
    noticeInfo: userInfo.value.noticeInfo || ''
  }
  showEditModal.value = true
}

// 关闭编辑资料弹窗
function closeEditModal() {
  showEditModal.value = false
}

// 保存资料
async function saveProfile() {
  if (!editProfile.value.nickName.trim()) {
    alert('请输入昵称')
    return
  }
  
  if (editProfile.value.nickName.length < 2 || editProfile.value.nickName.length > 20) {
    alert('昵称长度应在2-20个字符之间')
    return
  }
  
  saving.value = true
  try {
    const res = await request.put('/user/update', {
      nickName: editProfile.value.nickName,
      avatar: editProfile.value.avatar,
      sex: editProfile.value.sex,
      birthday: editProfile.value.birthday || null,
      school: editProfile.value.school,
      personIntroduction: editProfile.value.personIntroduction,
      noticeInfo: editProfile.value.noticeInfo
    })
    
    if (res.code === 200) {
      localStorage.setItem('nickName', editProfile.value.nickName)
      // 更新页面显示
      userInfo.value.nickName = editProfile.value.nickName
      userInfo.value.avatar = editProfile.value.avatar
      userInfo.value.sex = editProfile.value.sex
      userInfo.value.birthday = editProfile.value.birthday
      userInfo.value.school = editProfile.value.school
      userInfo.value.personIntroduction = editProfile.value.personIntroduction
      userInfo.value.noticeInfo = editProfile.value.noticeInfo
      
      closeEditModal()
      alert('保存成功~')
    } else {
      alert(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存失败:', error)
    alert('保存失败')
  } finally {
    saving.value = false
  }
}

// 上传头像
async function uploadAvatar(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  
  if (file.size > 15 * 1024 * 1024) {
    alert('文件大小不能超过15MB')
    return
  }
  
  avatarUploading.value = true
  avatarProgress.value = 0
  
  try {
    const res = await uploadFile({
      url: '/file/upload-avatar',
      file,
      onProgress: (percent) => {
        avatarProgress.value = percent
      }
    })
    
    if (res.code === 200 && res.data?.url) {
      editProfile.value.avatar = res.data.url
      alert('头像上传成功~')
    } else {
      alert(res.message || '上传失败')
    }
  } catch (error: any) {
    console.error('上传失败:', error)
    alert(error.message || '上传失败')
  } finally {
    avatarUploading.value = false
    avatarProgress.value = 0
    target.value = ''
  }
}

// 搜索处理
function handleSearch() {
  if (!searchKeyword.value.trim()) return
  router.push(`/search?keyword=${encodeURIComponent(searchKeyword.value.trim())}`)
}

// 退出登录
function logout() {
  localStorage.clear()
  router.push('/login')
}

// 开始私聊
async function startChat() {
  const token = localStorage.getItem('token')
  if (!token) {
    alert('请先登录')
    router.push('/login')
    return
  }
  
  try {
    // 创建或获取聊天会话，传递对方用户ID
    const res = await request.post('/chat/conversation/create', {
      targetUserId: userId.value
    })
    
    // 跳转到聊天页面
    router.push('/chat')
  } catch (error: any) {
    console.error('创建聊天失败:', error)
    alert(error.message || '创建聊天失败')
  }
}

// 获取图片URL
function getImageUrl(url: string | undefined): string {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) {
    // 如果是localhost的URL，去掉域名部分
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

function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  // 防止无限循环
  if (target.dataset.errorHandled) return
  target.dataset.errorHandled = 'true'
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
}

function handleCoverError(e: Event, originalCoverImage?: string) {
  const target = e.target as HTMLImageElement
  const currentSrc = target.src
  
  // 如果当前是缩略图加载失败，回退到原图
  if (currentSrc.includes('/thumbnails/') && originalCoverImage) {
    target.src = getImageUrl(originalCoverImage)
    return
  }
  
  // 原图也加载失败，隐藏图片显示渐变背景
  target.style.display = 'none'
}

// 获取性别文本
function getSexText(sex: number | undefined): string {
  if (sex === 1) return '男'
  if (sex === 0) return '女'
  return '未知'
}

// 去除HTML标签
function stripHtmlTags(str: string): string {
  if (!str) return ''
  return str.replace(/<[^>]*>/g, '')
}

// 格式化日期
function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

// 监听路由参数变化
watch(() => route.params.id, (newId, oldId) => {
  // 只有id真正变化时才重新获取
  if (newId !== oldId && route.name === 'UserSpace') {
    fetchUserInfo()
    fetchFollowStatus()
    fetchArticles(true)
  }
})

// 登录弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const dialogWidth = ref(window.innerWidth <= 480 ? '92%' : '420px')

// 登录过期处理
function handleAuthExpired() {
  showLoginDialog.value = true
}

function handleLoginSuccess() {
  showLoginDialog.value = false
  fetchUserInfo()
  fetchFollowStatus()
  fetchArticles(true)
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

onMounted(() => {
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  fetchUserInfo()
  fetchFollowStatus()
  fetchArticles(true)
})

onUnmounted(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
})
</script>

<style scoped>
.user-space-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
}

.user-space-page::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #f5f7fa;
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
  color: #409eff;
  cursor: pointer;
}

.logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.logo-text {
  display: inline;
}

/* 搜索框 */
.search-box {
  flex: 1;
  max-width: 400px;
  margin: 0 40px;
  position: relative;
}

.search-box input {
  width: 100%;
  height: 40px;
  padding: 0 45px 0 18px;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 14px;
  outline: none;
  transition: all 0.3s;
  background: white;
  color: #333;
}

.search-box input::placeholder {
  color: #999;
}

/* 隐藏原生搜索清除按钮 */
.search-box input[type="search"]::-webkit-search-cancel-button {
  -webkit-appearance: none;
  display: none;
}

.search-box input:focus {
  border-color: #409eff;
  background: white;
}

.search-btn {
  position: absolute;
  right: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  background: #409eff;
  border: none;
  border-radius: 50%;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.search-btn:hover {
  background: #66b1ff;
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
  font-size: 14px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
  transform: translateY(-2px);
}

.nav-btn.primary {
  background: #409eff;
  color: white;
  font-weight: 600;
}

.nav-btn.primary:hover {
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.4);
}

.nav-btn.logout {
  background: rgba(244, 67, 54, 0.2);
  color: #ff6b6b;
}

.nav-btn.logout:hover {
  background: rgba(244, 67, 54, 0.3);
}

/* 用户头部 */
.space-header {
  margin-top: 70px;
  height: 280px;
  background: #f5f7fa;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  position: relative;
  overflow: hidden;
}

/* 装饰圆圈 */
.space-header::before {
  content: '';
  position: absolute;
  top: -80px;
  right: -80px;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(79, 172, 254, 0.2) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
}

.space-header::after {
  content: '';
  position: absolute;
  bottom: -100px;
  left: -50px;
  width: 250px;
  height: 250px;
  background: radial-gradient(circle, rgba(118, 75, 162, 0.15) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 20px;
  display: flex;
  align-items: flex-end;
  height: 100%;
}

.user-avatar {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  border: 4px solid white;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  object-fit: cover;
}

.user-info {
  margin-left: 30px;
  flex: 1;
  color: #333;
}

.username {
  font-size: 28px;
  font-weight: bold;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-badge {
  display: inline-block;
  background: rgba(64, 158, 255, 0.8);
  border: 1px solid rgba(64, 158, 255, 0.9);
  color: white;
  padding: 3px 12px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}

.user-badge.admin {
  background: #FF3B3F;
  border-color: transparent;
}

.user-intro {
  font-size: 14px;
  opacity: 0.9;
  margin-bottom: 15px;
}

.user-stats {
  display: flex;
  gap: 30px;
  font-size: 14px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  transition: all 0.3s;
}

.stat-item:hover {
  transform: scale(1.05);
}

.stat-value {
  font-size: 20px;
  font-weight: bold;
  color: #333;
}

.stat-label {
  opacity: 0.8;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.action-btn {
  padding: 10px 24px;
  border: 1px solid #ddd;
  background: white;
  color: #666;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s;
}

.action-btn:hover {
  border-color: #409eff;
  color: #409eff;
  transform: translateY(-2px);
}

.action-btn.primary {
  background: #409eff;
  border-color: #409eff;
  color: white;
}

.action-btn.primary:hover {
  background: #66b1ff;
  color: white;
}

.action-btn.chat-btn {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-btn.chat-btn svg {
  width: 16px;
  height: 16px;
}

.action-btn.chat-btn:hover {
  background: #409eff;
  color: white;
  border-color: #409eff;
}

/* 主内容 */
.main-content {
  max-width: 1200px;
  margin: 30px auto;
  padding: 0 20px;
  display: flex;
  gap: 20px;
}

.content-left {
  flex: 1;
}

.content-right {
  width: 320px;
}

/* 标签页 */
.tabs {
  background: white;
  border: 1px solid #eee;
  border-radius: 15px;
  padding: 0 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
  display: flex;
  gap: 40px;
}

.tab-item {
  padding: 18px 0;
  color: #666;
  font-size: 15px;
  cursor: pointer;
  position: relative;
  transition: all 0.3s;
  border-bottom: 3px solid transparent;
  display: flex;
  align-items: center;
  gap: 8px;
}

.tab-item svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.tab-item:hover {
  color: #409eff;
}

.tab-item.active {
  color: #409eff;
  border-bottom-color: #409eff;
  font-weight: 500;
}

.tab-badge {
  margin-left: 6px;
  color: #999;
  font-size: 13px;
}

/* 过滤器 */
.filter-bar {
  background: white;
  border: 1px solid #eee;
  border-radius: 15px;
  padding: 15px 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
  display: flex;
  gap: 15px;
}

.filter-btn {
  padding: 8px 20px;
  border: 1px solid #eee;
  background: #f8f9fa;
  color: #666;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.filter-btn:hover {
  background: #eee;
  transform: translateY(-2px);
}

.filter-btn.active {
  background: #409eff;
  color: white;
  border-color: #409eff;
}

/* 文章列表 */
.article-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.article-card {
  background: #f7f9fc;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 15px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 4px 15px rgba(0,0,0,0.08);
}

.article-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.article-cover {
  width: 100%;
  height: 160px;
  object-fit: cover;
  display: block;
  transition: opacity 0.3s ease-in-out;
}

/* 懒加载状态样式 */
.article-cover.lazy-loading {
  opacity: 0;
}

.article-cover.lazy-loaded {
  opacity: 1;
}

.article-cover.lazy-error {
  opacity: 0.5;
}

.no-cover-placeholder {
  width: 100%;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  text-align: center;
  background: #e8e8e8;
}

.placeholder-title {
  color: #666;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.3;
  max-width: 100%;
  word-break: break-word;
  text-align: center;
  padding: 0 4px;
}

/* 封面区域容器 */
.article-card .cover-wrapper {
  width: 100%;
  height: 160px;
  background: #f0f0f0;
  overflow: hidden;
  position: relative;
}

.article-info {
  padding: 15px;
}

.article-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 10px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}

.article-meta {
  display: flex;
  gap: 15px;
  font-size: 12px;
  color: #999;
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  margin-top: 30px;
}

.page-btn {
  padding: 10px 24px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 20px;
  color: #666;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.page-btn:hover:not(:disabled) {
  background: white;
  border-color: #333;
  color: #333;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: #666;
  font-size: 14px;
}

/* 加载状态 */
.loading-state,
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
  font-size: 16px;
  background: white;
  border: 1px solid #eee;
  border-radius: 15px;
}

/* 右侧边栏 */
.sidebar-card {
  background: white;
  border: 1px solid #eee;
  border-radius: 15px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f0f0f0;
}

.coin-info {
  display: flex;
  justify-content: space-around;
}

.coin-item {
  text-align: center;
}

.coin-value {
  font-size: 24px;
  font-weight: bold;
  color: #409eff;
  margin-bottom: 4px;
}

.coin-label {
  font-size: 12px;
  color: #999;
}

.notice-content {
  font-size: 14px;
  color: #666;
  line-height: 1.6;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #eee;
  min-height: 60px;
}

/* 个人信息卡片 */
.user-detail-card {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #666;
}

.detail-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.detail-icon svg {
  width: 100%;
  height: 100%;
  fill: #999;
}

/* 直播间 */
.live-status {
  text-align: center;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #eee;
}

.live-tip {
  font-size: 14px;
  color: #999;
  margin-bottom: 12px;
}

.live-btn {
  background: white;
  color: #409eff;
  border: 1px solid #409eff;
  padding: 10px 24px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.live-btn:hover {
  background: #409eff;
  color: white;
  transform: scale(1.02);
}

/* 响应式 */
@media (max-width: 900px) {
  .content-right {
    display: none;
  }
}

@media (max-width: 768px) {
  .navbar {
    padding: 0 12px;
    height: 55px;
  }
  
  .logo {
    font-size: 18px;
    flex-shrink: 0;
  }
  
  .search-box {
    flex: 1;
    margin: 0 10px;
    min-width: 0;
  }
  
  .search-box input {
    height: 34px;
    font-size: 12px;
  }
  
  .nav-right {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }
  
  .nav-btn {
    padding: 6px 10px;
    font-size: 12px;
    white-space: nowrap;
    border-radius: 15px;
  }
  
  .space-header {
    margin-top: 60px;
    height: auto;
    min-height: 200px;
    padding: 25px 15px;
  }
  
  .header-content {
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 15px;
  }
  
  .user-avatar {
    width: 80px;
    height: 80px;
  }
  
  .user-info {
    margin-left: 0;
  }
  
  .username {
    font-size: 20px;
    justify-content: center;
  }
  
  .user-bio {
    font-size: 13px;
  }
  
  .user-stats {
    justify-content: center;
    gap: 25px;
    flex-wrap: wrap;
  }
  
  .stat-item {
    text-align: center;
  }
  
  .stat-value {
    font-size: 18px;
  }
  
  .header-actions {
    margin-top: 15px;
    justify-content: center;
    flex-wrap: wrap;
    gap: 10px;
  }
  
  .main-content {
    padding: 15px;
    flex-direction: column;
  }
  
  .content-left {
    width: 100%;
  }
  
  .tab-header {
    padding: 10px 12px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  
  .tab-btn {
    padding: 8px 14px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .articles-list {
    padding: 12px;
  }
  
  .article-card {
    padding: 12px;
  }
  
  .article-info h3 {
    font-size: 14px;
  }
  
  .article-summary {
    font-size: 12px;
    -webkit-line-clamp: 2;
  }
  
  .article-cover {
    width: 90px;
    height: 60px;
  }
}

@media (max-width: 480px) {
  .navbar {
    padding: 0 8px;
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
  
  .search-box {
    display: none;
  }
  
  .nav-right {
    gap: 5px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  
  .nav-btn {
    padding: 5px 8px;
    font-size: 11px;
    white-space: nowrap;
  }
  
  .space-header {
    margin-top: 55px;
    min-height: 180px;
    padding: 20px 12px;
  }
  
  .user-avatar {
    width: 70px;
    height: 70px;
  }
  
  .username {
    font-size: 18px;
  }
  
  .user-bio {
    font-size: 12px;
  }
  
  .user-stats {
    gap: 15px;
  }
  
  .stat-value {
    font-size: 16px;
  }
  
  .stat-label {
    font-size: 11px;
  }
  
  .header-actions {
    gap: 8px;
  }
  
  .action-btn {
    padding: 8px 14px;
    font-size: 12px;
  }
  
  .main-content {
    padding: 12px 10px;
  }
  
  .tab-header {
    padding: 8px 10px;
  }
  
  .tab-btn {
    padding: 6px 10px;
    font-size: 12px;
  }
  
  .articles-list {
    padding: 10px;
  }
  
  .article-card {
    padding: 10px;
    flex-direction: column-reverse;
    gap: 10px;
  }
  
  .article-info {
    width: 100%;
  }
  
  .article-info h3 {
    font-size: 14px;
  }
  
  .article-summary {
    font-size: 11px;
  }
  
  .article-cover {
    width: 100%;
    height: 130px;
    border-radius: 8px;
  }
  
  .article-meta {
    font-size: 11px;
  }
  
  /* 编辑资料弹窗 */
  .modal-content {
    width: 95%;
    max-height: 90vh;
    border-radius: 15px;
  }
  
  .modal-header h2 {
    font-size: 18px;
  }
  
  .modal-body {
    padding: 20px 15px;
  }
}

/* 编辑资料弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: white;
  border-radius: 20px;
  width: 90%;
  max-width: 500px;
  max-height: 85vh;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from { transform: translateY(30px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.modal-header {
  padding: 20px 25px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h2 {
  font-size: 20px;
  font-weight: 600;
  color: #333;
  margin: 0;
}

.modal-close {
  width: 32px;
  height: 32px;
  border: none;
  background: #f5f5f5;
  border-radius: 50%;
  font-size: 20px;
  color: #666;
  cursor: pointer;
  transition: all 0.2s;
}

.modal-close:hover {
  background: #e8e8e8;
  color: #333;
}

.modal-body {
  padding: 25px;
  max-height: 55vh;
  overflow-y: auto;
}

.edit-avatar-section {
  text-align: center;
  margin-bottom: 25px;
}

.edit-avatar-upload {
  position: relative;
  width: 100px;
  height: 100px;
  margin: 0 auto;
  cursor: pointer;
}

.edit-avatar-preview {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid #f0f0f0;
  transition: all 0.3s;
}

.edit-avatar-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.3s;
}

.edit-avatar-overlay span {
  color: white;
  font-size: 12px;
}

.edit-avatar-upload:hover .edit-avatar-overlay {
  opacity: 1;
}

.edit-avatar-upload:hover .edit-avatar-preview {
  border-color: #409eff;
}

.edit-file-input {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

/* 头像上传进度条 */
.edit-avatar-progress {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  border: 3px solid #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.edit-avatar-progress .progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  background: rgba(64, 158, 255, 0.3);
  transition: height 0.3s ease;
}

.edit-avatar-progress .progress-text {
  position: relative;
  z-index: 1;
  font-size: 14px;
  font-weight: 600;
  color: #409eff;
}

.edit-form-item {
  margin-bottom: 18px;
}

.edit-form-item > label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
}

.edit-form-item > label .required {
  color: #ff6b9d;
}

.edit-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
}

.edit-form-item input,
.edit-form-item textarea,
.edit-form-item select {
  width: 100%;
  padding: 12px 15px;
  border: 1.5px solid #e0e0e0;
  border-radius: 10px;
  font-size: 14px;
  color: #333;
  transition: all 0.3s;
  background: white;
}

.edit-form-item input:focus,
.edit-form-item textarea:focus,
.edit-form-item select:focus {
  outline: none;
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
}

.edit-form-item select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23666' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
}

.edit-form-item textarea {
  resize: vertical;
  min-height: 60px;
}

.modal-footer {
  padding: 20px 25px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  gap: 12px;
}

.modal-cancel {
  flex: 1;
  padding: 12px;
  background: white;
  border: 1.5px solid #e0e0e0;
  border-radius: 10px;
  color: #666;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
}

.modal-cancel:hover {
  border-color: #999;
  color: #333;
}

.modal-submit {
  flex: 1;
  padding: 12px;
  background: #409eff;
  border: none;
  border-radius: 10px;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
}

.modal-submit:hover:not(:disabled) {
  background: #66b1ff;
}

.modal-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
