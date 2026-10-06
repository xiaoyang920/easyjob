import type { RouteLocationRaw, Router } from 'vue-router'

/**
 * 站内返回导航。
 *
 * Vue Router 会把上一条站内记录的路径写进 history.state.back：
 * - 有值：用户是从站内某个页面过来的，应该回到那里；
 * - 为 null：直接打开链接、刷新后新标签页打开等情况，没有可返回的站内页面，
 *   此时调用 router.back() 会离开本站，必须改走兜底页面。
 */
export function getPreviousPath(): string | null {
  const back = window.history.state?.back
  return typeof back === 'string' ? back : null
}

/** 返回上一页；没有站内上一页时进入兜底页面（replace，避免再多出一条记录）。 */
export function goBackOr(router: Router, fallback: RouteLocationRaw) {
  if (getPreviousPath()) {
    router.back()
  } else {
    router.replace(fallback)
  }
}

/**
 * 完成操作后返回上一页，但上一页本身已经失效时（例如被删除文章的详情页、编辑页）改走兜底页面。
 * @param isStale 判断上一页路径是否已失效
 */
export function goBackUnless(
  router: Router,
  isStale: (previousPath: string) => boolean,
  fallback: RouteLocationRaw,
) {
  const previous = getPreviousPath()
  if (previous && !isStale(previous)) {
    router.back()
  } else {
    router.replace(fallback)
  }
}

/**
 * 进入指定页面：如果上一页正是目标页面（例如从文章详情进入编辑，发布后回到该文章），
 * 直接后退，避免历史记录里出现两条相同页面；否则用 replace 替换当前页。
 */
export function returnTo(router: Router, targetPath: string) {
  if (getPreviousPath() === targetPath) {
    router.back()
  } else {
    router.replace(targetPath)
  }
}
