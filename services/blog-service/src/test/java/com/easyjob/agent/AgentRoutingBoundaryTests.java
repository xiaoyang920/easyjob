package com.easyjob.agent;

import com.easyjob.rpc.v1.AgentQuery;
import com.google.protobuf.Descriptors.ServiceDescriptor;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.core.type.filter.AnnotationTypeFilter;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.lang.reflect.Method;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class AgentRoutingBoundaryTests {
    @Test void browserAgentEndpointsAreOwnedByPythonRatherThanJavaControllers() throws Exception {
        ClassPathScanningCandidateComponentProvider scanner = new ClassPathScanningCandidateComponentProvider(false);
        scanner.addIncludeFilter(new AnnotationTypeFilter(RestController.class));
        for (BeanDefinition bean : scanner.findCandidateComponents("com.easyjob")) {
            Class<?> controller = Class.forName(bean.getBeanClassName(), false, getClass().getClassLoader());
            RequestMapping prefix = AnnotatedElementUtils.findMergedAnnotation(controller, RequestMapping.class);
            for (Method method : controller.getDeclaredMethods()) {
                RequestMapping suffix = AnnotatedElementUtils.findMergedAnnotation(method, RequestMapping.class);
                if (suffix == null) continue;
                for (String base : paths(prefix)) for (String path : paths(suffix)) {
                    assertFalse((base + path).matches("/api/agent(?:/.*)?"),
                        () -> "Obsolete browser proxy: " + controller.getName() + "#" + method.getName());
                }
            }
        }
    }

    @Test void internalContractContainsNoChatOrStreamingRpc() {
        ServiceDescriptor agent = AgentQuery.getDescriptor().getFile().findServiceByName("AgentRpc");
        assertEquals(List.of("ServiceQuery"), agent.getMethods().stream().map(method -> method.getName()).toList());
        for (ServiceDescriptor service : AgentQuery.getDescriptor().getFile().getServices()) {
            assertTrue(service.getMethods().stream().noneMatch(method -> method.isClientStreaming() || method.isServerStreaming()));
        }
    }

    private static String[] paths(RequestMapping mapping) {
        return mapping == null || mapping.path().length == 0 ? new String[]{""} : mapping.path();
    }
}
