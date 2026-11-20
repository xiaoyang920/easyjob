package com.easyjob.gateway;

import io.netty.util.NetUtil;
import org.lionsoul.ip2region.xdb.Searcher;
import org.lionsoul.ip2region.xdb.Version;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/** Resolve a coarse location at ingress without passing the client IP downstream. */
@Component
final class ClientLocation {
    static final String CLIENT_IP_HEADER = "X-Easyjob-Client-IP";
    private static final Logger LOG = LoggerFactory.getLogger(ClientLocation.class);
    private final Set<InetAddress> trustedProxies;
    private final Searcher ipv4;
    private final Searcher ipv6;

    ClientLocation(@Value("${GATEWAY_TRUSTED_CLIENT_IP_PROXIES:}") String trustedProxies,
                   @Value("${GATEWAY_IP_LOCATION_DB_DIR:./temp/ip-location}") String databaseDirectory) {
        this.trustedProxies = Arrays.stream(trustedProxies.split(","))
                .map(String::strip).filter(value -> !value.isEmpty()).map(value -> {
                    InetAddress address = literalAddress(value);
                    if (address == null) {
                        throw new IllegalArgumentException("Trusted client IP proxies must be literal IP addresses");
                    }
                    return address;
                }).collect(Collectors.toUnmodifiableSet());
        ipv4 = load(databaseDirectory, "ip2region_v4.xdb", Version.IPv4);
        ipv6 = load(databaseDirectory, "ip2region_v6.xdb", Version.IPv6);
    }

    private static Searcher load(String directory, String name, Version version) {
        if (directory.isBlank()) return null;
        Path file = Path.of(directory, name);
        if (!Files.isRegularFile(file)) return null;
        try {
            Searcher.verifyFromFile(file.toString());
            return Searcher.newWithBuffer(version, Searcher.loadContentFromFile(file.toString()));
        } catch (Exception error) {
            LOG.warn("Failed to load IP location database {}", name);
            return null;
        }
    }

    private static InetAddress literalAddress(String value) {
        if (value.length() > 45 || !value.matches("[0-9a-fA-F:.]+")) return null;
        return NetUtil.createInetAddressFromIpAddressString(value);
    }

    InetAddress clientAddress(ServerHttpRequest request) {
        InetSocketAddress remote = request.getRemoteAddress();
        InetAddress peer = remote == null ? null : remote.getAddress();
        if (peer == null || !trustedProxies.contains(peer)) return peer;
        List<String> forwarded = request.getHeaders().getOrEmpty(CLIENT_IP_HEADER);
        return forwarded.size() == 1 ? literalAddress(forwarded.getFirst().strip()) : null;
    }

    String resolve(ServerHttpRequest request) {
        if (ipv4 == null && ipv6 == null) return null;
        InetAddress address = clientAddress(request);
        if (address == null || address.isAnyLocalAddress() || address.isLoopbackAddress()
                || address.isSiteLocalAddress() || address.isLinkLocalAddress() || address.isMulticastAddress()) return null;
        byte[] ip = address.getAddress();
        // ip2region labels other special-purpose networks as Reserved.
        Searcher searcher = ip.length == 4 ? ipv4 : ipv6;
        if (searcher == null) return null;
        try {
            return cityLabel(searcher.search(ip));
        } catch (Exception error) {
            return null;
        }
    }

    static String cityLabel(String region) {
        if (region == null) return null;
        String[] fields = region.split("\\|", -1);
        if (fields.length != 5 || !placeName(fields[2])) return null;
        Set<String> names = new LinkedHashSet<>();
        for (int index = 0; index < 3; index++) {
            if (placeName(fields[index])) names.add(fields[index]);
        }
        return String.join(" / ", names);
    }

    private static boolean placeName(String value) {
        return !Set.of("reserved", "unknown", "lan", "private", "内网", "保留", "未知")
                .contains(value.toLowerCase(java.util.Locale.ROOT))
                && value.matches("[\\p{L}\\p{M}][\\p{L}\\p{M} .’'·()\\-]{0,59}");
    }
}
