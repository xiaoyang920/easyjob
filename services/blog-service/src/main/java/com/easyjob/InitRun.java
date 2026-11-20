package com.easyjob;

import com.easyjob.component.EsComponent;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Component
@org.springframework.core.annotation.Order(0)
public class InitRun implements ApplicationRunner {
    @Autowired
    private EsComponent esComponent;
    @Override
    public void run(ApplicationArguments args) throws Exception {
        esComponent.createIndex();
    }
}
