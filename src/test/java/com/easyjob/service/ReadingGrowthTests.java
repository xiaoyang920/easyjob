package com.easyjob.service;
import org.junit.jupiter.api.Test;
import java.time.Instant;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ReadingGrowthTests {
    final List<Map<String,Object>> rules=List.of(Map.of("level",0,"minSeconds",0L),Map.of("level",1,"minSeconds",3600L),Map.of("level",2,"minSeconds",18000L));
    @Test void thresholdsAreInclusiveAndNeverDowngradeEarnedLevels() {
        assertEquals(0,ReadingGrowthService.levelFor(3599,0,rules));
        assertEquals(1,ReadingGrowthService.levelFor(3600,0,rules));
        assertEquals(2,ReadingGrowthService.levelFor(18000,0,rules));
        assertEquals(2,ReadingGrowthService.levelFor(0,2,rules));
        var higher=List.<Map<String,Object>>of(Map.of("level",0,"minSeconds",0L),Map.of("level",1,"minSeconds",7200L));
        assertEquals(1,ReadingGrowthService.levelFor(3600,1,higher));
    }
    @Test void onlyServerElapsedActiveIntervalsAreCredited() {
        var t=Instant.parse("2026-10-05T00:00:00Z");
        assertEquals(15042,ReadingGrowthService.creditMillis(t,t.plusMillis(15042),true));
        assertEquals(0,ReadingGrowthService.creditMillis(t,t.plusSeconds(15),false));
        assertEquals(0,ReadingGrowthService.creditMillis(t,t.minusSeconds(1),true));
        assertEquals(30000,ReadingGrowthService.creditMillis(t,t.plusSeconds(40),true));
        assertEquals(0,ReadingGrowthService.creditMillis(t,t.plusSeconds(46),true));
    }
}
