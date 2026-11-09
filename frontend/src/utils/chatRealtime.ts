import {ensureAccessToken} from './authSession'
import {eventBus,EVENT_AUTH_CHANGED,EVENT_AUTH_EXPIRED} from './eventBus'

type Listener=(event:any)=>void
const listeners=new Set<Listener>()
let socket:WebSocket|null=null,generation=0,connecting=false
let retry:ReturnType<typeof setTimeout>|undefined,heartbeat:ReturnType<typeof setInterval>|undefined
function emit(event:any){for(const listener of listeners){try{listener(event)}catch{/* One page must not stop the shared transport. */}}}
function close(){generation++;connecting=false;clearTimeout(retry);clearInterval(heartbeat);const prior=socket;socket=null;if(prior){prior.onclose=null;prior.close()}}
async function connect(){
  if(!listeners.size || connecting || socket || !localStorage.getItem('token'))return
  const run=generation;connecting=true
  try{
    const token=await ensureAccessToken();if(run!==generation || !listeners.size || !token)return
    const transport=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/chat?token=${encodeURIComponent(token)}`);socket=transport
    transport.onopen=()=>{if(socket!==transport)return;emit({type:'connected'});heartbeat=setInterval(()=>{if(transport.readyState===WebSocket.OPEN)transport.send(JSON.stringify({type:'ping'}))},30000)}
    transport.onmessage=event=>{if(socket!==transport)return;try{emit(JSON.parse(event.data))}catch{/* Ignore malformed frames; persisted API is authoritative. */}}
    transport.onclose=()=>{if(socket!==transport)return;socket=null;clearInterval(heartbeat);retry=setTimeout(()=>void connect(),3000)}
    transport.onerror=()=>transport.close()
  }catch{if(run===generation)retry=setTimeout(()=>void connect(),3000)}finally{if(run===generation)connecting=false}
}
export function subscribeChatEvents(listener:Listener){listeners.add(listener);void connect();if(socket?.readyState===WebSocket.OPEN)queueMicrotask(()=>listener({type:'connected'}));return()=>{listeners.delete(listener);if(!listeners.size)close()}}
eventBus.on(EVENT_AUTH_EXPIRED,close)
eventBus.on(EVENT_AUTH_CHANGED,()=>{close();void connect()})
