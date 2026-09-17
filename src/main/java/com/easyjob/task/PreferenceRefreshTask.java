package com.easyjob.task;

import com.easyjob.mapper.UserTagPreferenceMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Slf4j
public class PreferenceRefreshTask {
    @Autowired
    private UserTagPreferenceMapper userTagPreferenceMapper;

    @Scheduled(cron = "0 0 2 * * ?")
    public void refreshAllPreferences() {
        log.info("开始刷新用户标签偏好...");
        long start = System.currentTimeMillis();
        userTagPreferenceMapper.refreshAllPreferences();
        log.info("用户标签偏好刷新完成，耗时 {}ms", System.currentTimeMillis() - start);
    }
}
