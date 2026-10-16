import { createRouter, createWebHistory } from 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    /**
     * AI 任务浮窗默认停靠在右下角；页面在该区域有固定控件时声明避让方式：
     * top - 底部是输入区，改停在顶部；above-actions - 窄屏右下角有浮动按钮组，排到按钮组上方
     */
    aiRunDock?: 'top' | 'above-actions'
  }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition || { top: 0, left: 0 }
  },
  routes: [
    { path: '/account-security', name: 'AccountSecurity', component: () => import('@/views/AccountSecurity.vue') },
    { path: '/password-reset', name: 'PasswordReset', component: () => import('@/views/PasswordReset.vue') },
    { path: '/admin', name: 'AdminConsole', component: () => import('@/views/AdminConsole.vue') },
    { path: '/ai-memory', name: 'MemoryManagement', component: () => import('@/views/MemoryManagement.vue') },
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/Home.vue')
    },
    {
      path: '/login',
      name: 'Login',
      redirect: { path: '/', query: { login: 'true' } }
    },
    {
      path: '/register',
      name: 'Register',
      redirect: { path: '/', query: { register: 'true' } }
    },
    {
      path: '/article/:id',
      name: 'ArticleDetail',
      component: () => import('@/views/ArticleDetail.vue'),
      meta: { aiRunDock: 'above-actions' }
    },
    {
      path: '/user-space/:id?',
      name: 'UserSpace',
      component: () => import('@/views/UserSpace.vue')
    },
    {
      path: '/create-article',
      name: 'CreateArticle',
      component: () => import('@/views/CreateArticle.vue')
    },
    {
      path: '/edit-article',
      name: 'EditArticle',
      component: () => import('@/views/EditArticle.vue')
    },
    {
      path: '/draft-box',
      name: 'DraftBox',
      component: () => import('@/views/DraftBox.vue')
    },
    {
      path: '/edit-profile',
      name: 'EditProfile',
      component: () => import('@/views/EditProfile.vue')
    },
    {
      path: '/followers-following',
      name: 'FollowersFollowing',
      component: () => import('@/views/FollowersFollowing.vue')
    },
    {
      path: '/search',
      name: 'Search',
      component: () => import('@/views/SearchResult.vue')
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/Chat.vue'),
      meta: { aiRunDock: 'top' }
    },
    {
      path: '/notifications',
      name: 'Notifications',
      component: () => import('@/views/Notifications.vue')
    },
    {
      path: '/ai-chat',
      name: 'AiChat',
      component: () => import('@/views/AiChat.vue')
    }
  ]
})

// 路由守卫 - 需要登录的页面
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const needAuth = ['AccountSecurity', 'AdminConsole', 'CreateArticle', 'EditArticle', 'DraftBox', 'EditProfile', 'FollowersFollowing', 'Chat', 'AiChat', 'MemoryManagement', 'Notifications']
  
  if (needAuth.includes(to.name as string) && !token) {
    // 跳转到首页并触发登录弹窗
    next({ path: '/', query: { login: 'true', redirect: to.fullPath } })
  } else {
    next()
  }
})

export default router
