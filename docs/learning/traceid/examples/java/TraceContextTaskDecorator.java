package com.easyjob.observability;

import io.opentelemetry.context.Context;
import org.springframework.core.task.TaskDecorator;

public final class TraceContextTaskDecorator implements TaskDecorator {
    @Override public Runnable decorate(Runnable task) {
        return Context.current().wrap(task);
    }
}
