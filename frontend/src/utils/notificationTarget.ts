export type NotificationTarget = { type:number; articleId?:number|string|null; targetId?:number|string|null }
export function isReviewNotification(type:number) { return type === 6 || type === 7 }
export function notificationPath(n:NotificationTarget):string|undefined {
  if(n.type===7 && n.articleId) {
    const query=new URLSearchParams({articleId:String(n.articleId)})
    if(n.targetId) query.set('revisionId',String(n.targetId))
    return `/draft-box?${query}`
  }
  if(n.articleId) {
    const hash=n.targetId && (n.type===1 || n.type===2) ? `#comment-${n.targetId}` : ''
    return `/article/${n.articleId}${hash}`
  }
  if(n.type===4 && n.targetId) return `/user-space/${n.targetId}`
}
