package com.easyjob.growth;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.junit.jupiter.api.*;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

@SuppressWarnings({"unchecked","rawtypes"})
class GrowthReservationsTests {
    StringRedisTemplate redis;HashOperations hashes;GrowthReservations service;Cache<String,Boolean> cache;
    final AtomicLong nanos=new AtomicLong();long releaseResult=1;int probes;Deque<List<String>> responses;
    @BeforeEach void setup(){
        redis=mock(StringRedisTemplate.class);hashes=mock(HashOperations.class);when(redis.opsForHash()).thenReturn(hashes);
        cache=Caffeine.newBuilder().ticker(nanos::get).expireAfterWrite(Duration.ofSeconds(1)).maximumSize(10000).build();
        responses=new ArrayDeque<>(List.of(List.of("SOLD_OUT"),List.of("ACCEPTED","new-reservation")));
        doAnswer(call->{RedisScript script=call.getArgument(0);if(script.getResultType()==Long.class)return releaseResult;probes++;return responses.removeFirst();})
            .when(redis).execute(any(RedisScript.class),anyList(),any(Object[].class));
        service=new GrowthReservations(redis,new ObjectMapper(),cache);
    }
    String reserve(){return service.reserve("activity",7,"request",0,Long.MAX_VALUE,120);}
    @Test void soldOutCacheSuppressesFurtherLuaProbes(){assertThrows(BusinessException.class,this::reserve);assertThrows(BusinessException.class,this::reserve);assertEquals(1,probes);}
    @Test void expiryIsMeasuredFromWriteAndHotReadsDoNotKeepItAlive(){
        assertThrows(BusinessException.class,this::reserve);nanos.set(900_000_000);assertThrows(BusinessException.class,this::reserve);
        nanos.set(1_000_000_001);assertEquals("new-reservation",reserve());assertEquals(2,probes);
    }
    @Test void successfulReleaseInvalidatesOnlyThatActivity(){
        assertThrows(BusinessException.class,this::reserve);cache.put("other",true);assertTrue(service.release("activity","old-reservation"));
        assertEquals("new-reservation",reserve());assertEquals(Boolean.TRUE,cache.getIfPresent("other"));
    }
    @Test void failedReleaseDoesNotClaimInventoryHasReturned(){
        assertThrows(BusinessException.class,this::reserve);releaseResult=0;assertFalse(service.release("activity","missing"));assertThrows(BusinessException.class,this::reserve);assertEquals(1,probes);
    }
    @Test void existingUserClaimStillReturnsOriginalReservationWhileSoldOut(){
        assertThrows(BusinessException.class,this::reserve);when(hashes.get("growth:{activity}:users","7")).thenReturn("original");assertEquals("original",reserve());assertEquals(1,probes);
    }
    @Test void capacityEvictionDoesNotClearEveryActivityAtOnce(){
        for(int i=0;i<20000;i++)cache.put("activity-"+i,true);cache.cleanUp();assertTrue(cache.estimatedSize()<=10000);assertTrue(cache.estimatedSize()>0);
    }
}
