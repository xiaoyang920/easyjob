-- KEYS and ARGV[1..7] retain their existing business meanings.
-- Optional ARGV[8..9] carry trace context, never user authorization.
local expected={'string','string','hash','hash','stream','string'}
for i=1,6 do
 local kind=redis.call('TYPE',KEYS[i]).ok
 if kind~='none' and kind~=expected[i] then return {'UNAVAILABLE'} end
end
if redis.call('GET',KEYS[1])~=ARGV[1] then return {'UNAVAILABLE'} end
local previous=redis.call('HGET',KEYS[3],ARGV[2])
if previous then return {'ACCEPTED',previous} end
local t=redis.call('TIME'); local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
if now<tonumber(ARGV[5]) or now>=tonumber(ARGV[6]) then return {'INACTIVE'} end
local n=redis.call('GET',KEYS[2]); if not n then return {'UNAVAILABLE'} end
if tonumber(n)<=0 then return {'SOLD_OUT'} end
local limit=redis.call('INCR',KEYS[6]); if limit==1 then redis.call('PEXPIRE',KEYS[6],1000) end
if limit>5 then return {'LIMITED'} end
local item=cjson.encode({activityId=ARGV[1],userId=ARGV[2],requestId=ARGV[3],reservationId=ARGV[4],expiresAt=now+tonumber(ARGV[7])*1000})
redis.call('DECR',KEYS[2])
redis.call('HSET',KEYS[3],ARGV[2],ARGV[4])
redis.call('HSET',KEYS[4],ARGV[4],item)
redis.call('XADD',KEYS[5],'*','body',item,'traceparent',ARGV[8] or '',
 'tracestate',ARGV[9] or '','enqueued_at',tostring(now))
return {'ACCEPTED',ARGV[4]}
