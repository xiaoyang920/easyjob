package com.easyjob.security;
import com.easyjob.security.IdentityTokens.Principal;
public final class RequestIdentity {
    private static final ThreadLocal<IdentityTokens.Principal> CURRENT=new ThreadLocal<>();
    public static IdentityTokens.Principal get(){return CURRENT.get();}
    public static AutoCloseable use(IdentityTokens.Principal identity){Principal previous=CURRENT.get();CURRENT.set(identity);return ()->{if(previous==null)CURRENT.remove();else CURRENT.set(previous);};}
    static void set(IdentityTokens.Principal identity){CURRENT.set(identity);}
    static void clear(){CURRENT.remove();}
    private RequestIdentity(){}
}
