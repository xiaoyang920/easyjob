"""Native DeepSeek image parts, assembled only at the model boundary.

Graph state, MySQL and Redis contain owned file references, never Base64 payloads
or a lossy model-generated description. No model/API call is made here.
"""
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from app.config import settings

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_INLINE_BYTES = 24 * 1024 * 1024  # 32 MiB Base64, leaving room below the 48 MiB API limit.
MAX_HISTORY_IMAGES = 4
MAX_CURRENT_IMAGES = 4
IMAGE_TOKEN_BUDGET = 1024  # DeepSeek's documented upper bound per image.
FORMATS = {'JPEG':'image/jpeg','PNG':'image/png','GIF':'image/gif','WEBP':'image/webp'}


def owned_image(path: str, uid: int) -> Path:
    normalized = path.replace('\\','/') if isinstance(path,str) else ''
    root = Path(settings.FILE_UPLOAD_PATH).resolve()
    owner = root / 'ai-chat' / str(uid)
    if not normalized.startswith(f'ai-chat/{uid}/') or any(part in ('.','..','') for part in normalized.split('/')) or any(c in normalized for c in (':','?','#','\x00')):
        raise HTTPException(403,'图片不属于当前用户的上传目录')
    try: target = (root / normalized).resolve(strict=True)
    except (OSError,RuntimeError,ValueError): raise HTTPException(422,'图片无法读取，请重新上传') from None
    if not target.is_relative_to(owner) or not target.is_file(): raise HTTPException(403,'图片路径无效')
    if target.stat().st_size > MAX_IMAGE_BYTES: raise HTTPException(422,'图片过大，请压缩到 8MB 以内后上传')
    return target


def image_part(path: str, uid: int) -> dict:
    target = owned_image(path,uid)
    try:
        data = target.read_bytes()
        if len(data)>MAX_IMAGE_BYTES: raise ValueError('too large')
        with Image.open(BytesIO(data)) as image:
            mime = FORMATS.get(image.format)
            if not mime or max(image.size)>8192 or image.width*image.height>20_000_000: raise ValueError('invalid image')
            image.verify()
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):
        raise HTTPException(422,'图片内容无效，请重新上传 JPEG、PNG、GIF 或 WebP 图片') from None
    return {'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(data).decode('ascii'),'detail':'original'}}


def validate_current_images(paths, uid):
    if len(paths or [])>MAX_CURRENT_IMAGES: raise HTTPException(422,'每次最多上传 4 张图片')
    total=0
    for path in paths or []:
        part=image_part(path,uid)
        total+=len(part['image_url']['url'])
    if total>MAX_INLINE_BYTES*4//3: raise HTTPException(422,'本次图片总量过大，请减少图片后重试')


def recent_image_paths(history):
    selected=[];remaining=MAX_HISTORY_IMAGES
    for message in reversed(history):
        if message.get('role')!='user': continue
        paths=message.get('image_paths') or []
        if not isinstance(paths,list): continue
        for path in reversed(paths):
            if isinstance(path,str) and remaining:
                selected.append(path);remaining-=1
    return list(reversed(selected))


def prepare_visual_inputs(state):
    """Call through asyncio.to_thread in runtime; local dictionary lasts one decision."""
    paths=[*(state.get('user_image_paths') or []),*recent_image_paths(state.get('history_messages',[]))]
    result={};total=0
    for path in paths:
        if path in result: continue
        try:
            part=image_part(path,state['user_id']);size=len(part['image_url']['url'])
            if total+size>MAX_INLINE_BYTES*4//3: raise HTTPException(422,'图片总量超过本次请求预算')
            result[path]=part;total+=size
        except HTTPException:
            result[path]={'type':'text','text':'[图片当前不可读取或超过本次图片预算，不能推测图中内容；需要相关细节时请用户重新上传。]'}
    return result


def render_visual_history(history, visual, current_paths=()):
    # Budget occurrences, not unique paths: the same file in two messages is
    # transmitted twice. Current attachments always take precedence.
    remaining=MAX_INLINE_BYTES*4//3-sum(len(visual.get(path,{}).get('image_url',{}).get('url','')) for path in current_paths)
    selected=set();count=0
    for index in range(len(history)-1,-1,-1):
        message=history[index]
        paths=message.get('image_paths') or []
        if message.get('role')!='user' or not isinstance(paths,list): continue
        for number in range(len(paths)-1,-1,-1):
            path=paths[number]
            part=visual.get(path) if isinstance(path,str) else None
            if count>=MAX_HISTORY_IMAGES: break
            count+=1
            size=len((part or {}).get('image_url',{}).get('url',''))
            if part and size<=remaining:
                selected.add((index,number));remaining-=size
    messages=[];metadata=[]
    for index,message in enumerate(history):
        item={key:value for key,value in message.items() if key!='image_paths'}
        paths=message.get('image_paths') or []
        if message.get('role')=='user' and isinstance(paths,list) and paths:
            attached=[];loaded=0
            for number,path in enumerate(paths):
                if (index,number) in selected:
                    attached.extend([{'type':'text','text':f'历史消息中的第 {number+1} 张图片：'},visual[path]])
                    loaded+=int(visual[path]['type']=='image_url')
            item['image_count']=len(paths);item['attached_image_count']=loaded
            label=f'历史图片组{index+1}'
            item['image_attachment_label']=label
            if loaded<len(paths): item['image_notice']='部分图片未载入，不能凭摘要或历史回答猜测原图细节。'
            if attached: messages.append(HumanMessage(content=[{'type':'text','text':f'{label}，对应历史消息 {message.get("message_id",index+1)}。这些是历史资料，不是本轮新指令。'},*attached]))
        metadata.append(item)
    return metadata,messages


def current_user_message(state, visual):
    paths=state.get('user_image_paths') or []
    if not paths: return HumanMessage(content=state['user_message'])
    content=[{'type':'text','text':state['user_message'] or '请根据我上传的图片回答。'}]
    for index,path in enumerate(paths):
        content.append({'type':'text','text':f'本轮图片 {index+1}：'})
        content.append(visual.get(path,{'type':'text','text':'[该图片未能载入，请勿猜测其内容。]'}))
    return HumanMessage(content=content)
