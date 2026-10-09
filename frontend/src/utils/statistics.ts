export type Daily = {date:string;newUsers:number;newArticles:number;readingMillis:number;readingUsers:number}
export type Distribution = {name:string;count:number}
export type StatisticsReport = {days:number;from:string;to:string;generatedAt:string;daily:Daily[];articles:Distribution[];levels:Distribution[];periodNewUsers:number;periodNewArticles:number;periodReadingSeconds:number;periodReadingUsers:number;source:'business'|'evaluation'|'all'}

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
