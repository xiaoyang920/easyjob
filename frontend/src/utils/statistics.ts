export type Daily = {date:string;newUsers:number;newArticles:number;readingMillis:number;readingUsers:number}
export type Distribution = {name:string;count:number}
export type StatisticsReport = {days:number;from:string;to:string;generatedAt:string;daily:Daily[];articles:Distribution[];levels:Distribution[];periodNewUsers:number;periodNewArticles:number;periodReadingSeconds:number;periodReadingUsers:number;source:'business'|'evaluation'|'all'}

export type ExportJob = {
  jobNo: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  error?: string
}

type RealtimeEvent = { type: string; jobNo?: string }

export async function waitForStatisticsExport({
  start, read, subscribe, progress, signal,
}: {
  start: () => Promise<ExportJob>
  read: (jobNo: string) => Promise<ExportJob>
  subscribe: (listener: (event: RealtimeEvent) => void) => () => void
  progress: (job: ExportJob) => void
  signal: AbortSignal
}): Promise<ExportJob> {
  let jobNo: string | undefined
  let connected = false
  let needsRead = false
  let wake: (() => void) | undefined
  const deadline = Date.now() + 120_000
  // Subscribe before submitting so a fast worker cannot finish in between.
  const stop = subscribe(event => {
    if (event.type === 'connected') connected = true
    else if (event.type === 'disconnected') connected = false
    else if (event.type !== 'excel_export_finished' || (jobNo && event.jobNo !== jobNo)) return
    needsRead = true
    wake?.()
  })

  try {
    let job = await start()
    jobNo = job.jobNo
    while (job.status === 'pending' || job.status === 'running') {
      signal.throwIfAborted()
      progress(job)
      const remaining = deadline - Date.now()
      if (remaining <= 0) throw new Error('导出仍在处理中，再点一次可继续查询')
      if (!needsRead) {
        await new Promise<void>(resolve => {
          const finish = () => {
            clearTimeout(timer)
            signal.removeEventListener('abort', finish)
            wake = undefined
            resolve()
          }
          // A low-frequency check also covers dropped notifications on a live connection.
          const timer = setTimeout(finish, Math.min(remaining, connected ? 15_000 : 1_500))
          wake = finish
          signal.addEventListener('abort', finish, { once: true })
        })
      }
      signal.throwIfAborted()
      needsRead = false
      job = await read(jobNo)
    }
    return job
  } finally {
    stop()
  }
}

/** Include zero in every scale; avoid a zero denominator on empty days. */
export function chartCeiling(values:number[]) {
  const maximum=Math.max(0,...values.filter(Number.isFinite))
  if(maximum===0)return 1
  const magnitude=10**Math.floor(Math.log10(maximum))
  return Math.ceil(maximum/magnitude)*magnitude
}
export function chartPoints(values:number[],ceiling:number) {
  const span=Math.max(1,values.length-1),top=Math.max(1e-9,ceiling)
  return values.map((value,index)=>({x:48+index*584/span,y:178-Math.max(0,value)*146/top}))
}
/** A JSON error body must never be saved as an apparent spreadsheet. */
export async function spreadsheetBlob(value:unknown):Promise<Blob> {
  if(!(value instanceof Blob))throw new Error('导出返回格式异常，请重试')
  const signature=new Uint8Array(await value.slice(0,4).arrayBuffer())
  if(signature[0]===0x50 && signature[1]===0x4b && signature[2]===0x03 && signature[3]===0x04)return value
  if(value.size<65536){
    let response:{message?:unknown}|undefined
    try{response=JSON.parse(await value.text())}catch{/* Invalid binary responses also fail closed. */}
    if(typeof response?.message==='string')throw new Error(response.message)
  }
  throw new Error('导出未成功，请重试')
}
