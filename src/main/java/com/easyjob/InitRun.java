package com.easyjob;

import com.easyjob.agent.component.EsVectorStore;
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
    @Autowired
    private EsVectorStore esVectorStore;
    @Override
    public void run(ApplicationArguments args) throws Exception {
        esComponent.createIndex();
        esVectorStore.initIndex();
    }
}
