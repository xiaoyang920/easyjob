package com.easyjob.auth;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.easyjob.security.IdentityTokens;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.nimbusds.jose.jwk.RSAKey;
class JwksRotationTests {
    @TempDir Path folder;
    @Test @SuppressWarnings("unchecked")void publishesNextAndOldPublicKeysWithoutAnyPrivateFields()throws Exception{
        RSAKey current=new RSAKeyGenerator(2048).keyID("current").generate();RSAKey next=new RSAKeyGenerator(2048).keyID("next").generate();Path file=folder.resolve("auth-private.json");Files.writeString(file,current.toJSONString());
        AuthController controller=new AuthController(mock(AccountStore.class),mock(Sessions.class),mock(VerificationCodes.class),file.toString(),"issuer",false,1800);
        Files.writeString(folder.resolve("auth-published-public-next.json"),next.toPublicJWK().toJSONString());
        List<Map<String,Object>> keys=(List<Map<String,Object>>)controller.jwks().get("keys");assertEquals(2,keys.size());assertTrue(keys.stream().noneMatch(k->k.containsKey("d")||k.containsKey("p")));
        Files.writeString(file,next.toJSONString());Files.writeString(folder.resolve("auth-published-public-current.json"),current.toPublicJWK().toJSONString());
        AuthController restarted=new AuthController(mock(AccountStore.class),mock(Sessions.class),mock(VerificationCodes.class),file.toString(),"issuer",false,1800);
        keys=(List<Map<String,Object>>)restarted.jwks().get("keys");assertEquals(Set.of("current","next"),keys.stream().map(k->k.get("kid")).collect(java.util.stream.Collectors.toSet()));
    }
}
