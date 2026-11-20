package com.easyjob.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;

import java.net.InetSocketAddress;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class ClientLocationTests {
    private final ClientLocation location = new ClientLocation("172.29.253.2", "");

    @Test
    void onlyTheConfiguredProxyCanProvideASingleLiteralAddress() {
        assertEquals("1.2.3.4", location.clientAddress(request("172.29.253.2", "1.2.3.4")).getHostAddress());
        assertEquals("5.6.7.8", location.clientAddress(request("5.6.7.8", "1.2.3.4")).getHostAddress());
        assertEquals("127.0.0.1", location.clientAddress(request("127.0.0.1", "1.2.3.4")).getHostAddress());
        assertNull(location.clientAddress(request("172.29.253.2", "1.2.3.4, 5.6.7.8")));
        assertNull(location.clientAddress(request("172.29.253.2", "1.2.3.4", "5.6.7.8")));
        assertNull(location.clientAddress(request("172.29.253.2", "example.com")));
        assertNull(location.clientAddress(request("172.29.253.2")));
    }

    @Test
    void providerRecordsExposeOnlyGeographyAndRequireACity() {
        assertEquals("中国 / 浙江省 / 杭州市", ClientLocation.cityLabel("中国|浙江省|杭州市|电信|CN"));
        assertEquals("中国 / 上海市", ClientLocation.cityLabel("中国|上海市|上海市|联通|CN"));
        assertNull(ClientLocation.cityLabel("Reserved|Reserved|Reserved|0|0"));
        assertNull(ClientLocation.cityLabel("United States|California|0|0|US"));
        assertNull(location.resolve(request("1.2.3.4")));
    }

    private MockServerHttpRequest request(String peer, String... forwarded) {
        MockServerHttpRequest.BaseBuilder<?> builder = MockServerHttpRequest.post("/api/agent/chat")
                .remoteAddress(new InetSocketAddress(peer, 12345));
        if (forwarded.length > 0) builder.header(ClientLocation.CLIENT_IP_HEADER, forwarded);
        return builder.build();
    }
}
