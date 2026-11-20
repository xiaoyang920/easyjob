local marker=redis.call('GET',KEYS[1])
if marker~=ARGV[1] and marker~='PAUSED' then return 0 end
-- Pausing admission must not block settlement. Missing stock is still fail-closed.
if not redis.call('GET',KEYS[2]) then return 0 end
if not redis.call('HGET',KEYS[3],ARGV[2]) then return 0 end
if redis.call('SADD',KEYS[4],ARGV[2])==1 then redis.call('INCR',KEYS[2]) end
-- Keep user claim: this activity permits one order per user, including closed orders.
return 1
