package com.easyjob.config;

import com.easyjob.discovery.NacosDiscovery;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.web.context.WebServerInitializedEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.UnknownHostException;

@Component
@ConditionalOnProperty(name = "easyjob.nacos.enabled", havingValue = "true")
class BlogNacosRegistration {
    private static final Logger LOG = LoggerFactory.getLogger(BlogNacosRegistration.class);

    private final NacosDiscovery nacos;
    private final String advertiseHost;
    private int port;
    private String ip;
    private boolean ready;
    private boolean registered;

    BlogNacosRegistration(NacosDiscovery nacos,
                          @Value("${easyjob.nacos.advertise-host:127.0.0.1}") String advertiseHost) {
        this.nacos = nacos;
        this.advertiseHost = advertiseHost;
    }

    @EventListener
    synchronized void capturePort(WebServerInitializedEvent event) {
        if (!"management".equals(event.getApplicationContext().getServerNamespace())) {
            port = event.getWebServer().getPort();
        }
    }

    @EventListener
    synchronized void start(ApplicationReadyEvent event) {
        ready = true;
        renew();
    }

    @Scheduled(fixedDelay = 5000)
    synchronized void renew() {
        if (!ready || port == 0) {
            return;
        }
        try {
            if (ip == null) {
                InetAddress address = advertiseHost.isBlank()
                        ? InetAddress.getLocalHost()
                        : InetAddress.getByName(advertiseHost);
                ip = address.getHostAddress();
            }
            nacos.registerOrRenew(NacosDiscovery.BLOG_SERVICE, ip, port, registered);
            if (!registered) {
                LOG.info("Registered {} at {}:{} in Nacos", NacosDiscovery.BLOG_SERVICE, ip, port);
            }
            registered = true;
        } catch (RuntimeException | UnknownHostException exception) {
            LOG.warn("Nacos registration for {} will retry ({})",
                    NacosDiscovery.BLOG_SERVICE, exception.getClass().getSimpleName());
        }
    }

    @PreDestroy
    synchronized void stop() {
        ready = false;
        if (ip != null) {
            try {
                nacos.deregister(NacosDiscovery.BLOG_SERVICE, ip, port);
            } catch (RuntimeException exception) {
                LOG.warn("Nacos deregistration failed, the ephemeral instance will expire ({})",
                        exception.getClass().getSimpleName());
            }
        }
    }
}
