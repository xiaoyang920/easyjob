export type DiffLine={kind:'same'|'add'|'remove';text:string}
/** Bounded line comparison; long documents retain unchanged prefix/suffix without a quadratic allocation. */
export function compareLines(before:string,after:string):DiffLine[]{
 const a=before.split('\n'),b=after.split('\n');let start=0,end=0
 while(start<a.length && start<b.length && a[start]===b[start])start++
 while(end<a.length-start && end<b.length-start && a[a.length-1-end]===b[b.length-1-end])end++
 const x=a.slice(start,a.length-end),y=b.slice(start,b.length-end),result:DiffLine[]=a.slice(0,start).map(text=>({kind:'same',text}))
 if(x.length*y.length>250000){result.push(...x.map(text=>({kind:'remove' as const,text})),...y.map(text=>({kind:'add' as const,text})))}
 else{
  const width=y.length+1,dp=new Uint32Array((x.length+1)*width)
  for(let i=x.length-1;i>=0;i--)for(let j=y.length-1;j>=0;j--)dp[i*width+j]=x[i]===y[j]?1+dp[(i+1)*width+j+1]:Math.max(dp[(i+1)*width+j],dp[i*width+j+1])
  let i=0,j=0;while(i<x.length || j<y.length){if(i<x.length && j<y.length && x[i]===y[j])result.push({kind:'same',text:x[i++]}),j++;else if(j<y.length && (i===x.length || dp[i*width+j+1]>=dp[(i+1)*width+j]))result.push({kind:'add',text:y[j++]});else result.push({kind:'remove',text:x[i++]})}
 }
 result.push(...a.slice(a.length-end).map(text=>({kind:'same' as const,text})))
 return result
}
