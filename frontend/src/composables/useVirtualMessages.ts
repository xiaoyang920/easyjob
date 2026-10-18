import { computed, nextTick, onUnmounted, ref, watch, type Ref } from 'vue'

/** Variable-height window: message data stays intact; only visible rows keep a DOM tree. */
export function useVirtualMessages<T>(source: () => T[], container: Ref<HTMLElement | undefined>, key: (item:T,index:number)=>string, estimate:(item:T)=>number) {
  const top = ref(0), viewport = ref(800), revision = ref(0), spacer = ref<HTMLElement>()
  const heights = new Map<string,number>(), elements = new Map<HTMLElement,string>()
  let frame = 0, disposed = false
  let restoring = false, jumping = false
  const keys = computed(() => source().map(key))
  const offsets = computed(() => {
    revision.value
    const values = [0]
    source().forEach((item,index) => values.push(values[index]! + (heights.get(keys.value[index]!) ?? estimate(item))))
    return values
  })
  function indexAt(value:number) {
    let low=0,high=source().length
    while(low<high){const mid=(low+high)>>>1;if(offsets.value[mid+1]!<=value)low=mid+1;else high=mid}
    return low
  }
  const range = computed(() => source().length <= 60 ? {start:0,end:source().length} : {
    start:Math.max(0,indexAt(Math.max(0,top.value-1000))),
    end:Math.min(source().length,indexAt(top.value+viewport.value+1000)+1),
  })
  const items = computed(() => source().slice(range.value.start,range.value.end).map((item,n)=>({item,index:n+range.value.start})))
  const before = computed(()=>offsets.value[range.value.start] || 0)
  const after = computed(()=>Math.max(0,(offsets.value.at(-1) || 0)-(offsets.value[range.value.end] || 0)))
  function update() {
    frame=0;const el=container.value;if(!el || !spacer.value)return
    const origin=spacer.value.getBoundingClientRect().top-el.getBoundingClientRect().top+el.scrollTop
    top.value=Math.max(0,el.scrollTop-origin);viewport.value=el.clientHeight
  }
  function schedule(){if(!frame && !disposed && !jumping)frame=requestAnimationFrame(update)}
  const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(entries => {
    const el=container.value
    const atBottom=!!el && el.scrollHeight-el.scrollTop-el.clientHeight<40
    const anchorIndex=indexAt(top.value)
    let changed=false,correction=0
    for(const entry of entries){
      const node=entry.target as HTMLElement,id=elements.get(node);if(!id)continue
      const style=getComputedStyle(node),height=entry.borderBoxSize?.[0]?.blockSize ?? node.getBoundingClientRect().height
      const size=height+(parseFloat(style.marginTop)||0)+(parseFloat(style.marginBottom)||0)
      const index=keys.value.indexOf(id);if(index<0 || size<=0)continue
      const old=heights.get(id) ?? estimate(source()[index]!)
      if(Math.abs(old-size)<1)continue
      heights.set(id,size);changed=true
      if(index<anchorIndex)correction+=size-old
    }
    if(changed){revision.value++;void nextTick(()=>{if(el && !restoring && !jumping){if(atBottom)el.scrollTop=el.scrollHeight;else if(correction)el.scrollTop+=correction}schedule()})}
  })
  function measure(node: unknown) {
    if(!(node instanceof HTMLElement) || elements.has(node))return
    const id=node.dataset.virtualKey;if(!id)return
    elements.set(node,id);observer?.observe(node)
  }
  const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(schedule)
  watch(container,(current,previous)=>{previous?.removeEventListener('scroll',schedule);if(previous)resize?.unobserve(previous);current?.addEventListener('scroll',schedule,{passive:true});if(current)resize?.observe(current);void nextTick(schedule)},{flush:'post'})
  watch(keys, async current => {
    const keep=new Set(current)
    for(const id of heights.keys())if(!keep.has(id))heights.delete(id)
    await nextTick();for(const [node] of elements)if(!node.isConnected){observer?.unobserve(node);elements.delete(node)}
    schedule()
  },{flush:'pre'})
  async function scrollToIndex(index:number) {
    const el=container.value;if(!el || index<0 || index>=source().length)return false
    // Materialize the destination before touching scrollTop. When paging first
    // crosses the window threshold, the previous DOM can be much shorter and
    // would clamp the new position before its spacers have rendered.
    jumping=true;cancelAnimationFrame(frame);frame=0
    try {
      top.value=offsets.value[index] || 0;viewport.value=el.clientHeight
      await nextTick()
      const origin=spacer.value ? spacer.value.getBoundingClientRect().top-el.getBoundingClientRect().top+el.scrollTop : 0
      el.scrollTop=origin+(offsets.value[index] || 0)
      await nextTick();update()
    } finally {jumping=false;schedule()}
    return true
  }
  function captureAnchor() {
    update();const el=container.value,index=indexAt(top.value)
    const node=el ? Array.from(el.querySelectorAll<HTMLElement>('[data-virtual-key]')).find(row=>row.getBoundingClientRect().bottom>el.getBoundingClientRect().top) : undefined
    return {key:node?.dataset.virtualKey || keys.value[index],pixel:node && el ? node.getBoundingClientRect().top-el.getBoundingClientRect().top : 0}
  }
  async function restoreAnchor(anchor:ReturnType<typeof captureAnchor>) {
    const index=keys.value.indexOf(anchor.key || '');
    if(index<0)return
    restoring=true
    try {
      await scrollToIndex(index)
      // Measurements may arrive after the new window mounts. Correct against the
      // actual element for a few frames instead of trusting estimated row heights.
      for(let pass=0;pass<4;pass++) {
        await nextTick();await new Promise<void>(resolve=>{const timer=setTimeout(()=>{cancelAnimationFrame(id);resolve()},50);const id=requestAnimationFrame(()=>{clearTimeout(timer);resolve()})})
        const el=container.value,node=el?.querySelector<HTMLElement>(`[data-virtual-key="${CSS.escape(anchor.key || '')}"]`)
        if(el && node)el.scrollTop+=node.getBoundingClientRect().top-el.getBoundingClientRect().top-anchor.pixel
        update()
      }
    } finally {restoring=false}
  }
  watch(range,async()=>{await nextTick();for(const [node] of elements)if(!node.isConnected){observer?.unobserve(node);elements.delete(node)}})
  onUnmounted(()=>{disposed=true;cancelAnimationFrame(frame);observer?.disconnect();resize?.disconnect();container.value?.removeEventListener('scroll',schedule);elements.clear();heights.clear()})
  return {items,before,after,spacer,measure,scrollToIndex,schedule,captureAnchor,restoreAnchor}
}
