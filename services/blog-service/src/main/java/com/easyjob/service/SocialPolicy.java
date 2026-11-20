package com.easyjob.service;

/** One decision used for both UI capabilities and every message admission. */
public final class SocialPolicy {
    private SocialPolicy() {}
    public record Facts(boolean active, boolean blocked, boolean mutual, String state,
                        Long initiator, long actor, boolean allowRequests) {}
    public record Decision(boolean canMessage, boolean canSendRich, String reason) {}
    public static Decision decide(Facts f) {
        if (!f.active() || f.blocked()) return new Decision(false,false,"暂时无法向该用户发送消息");
        if (f.mutual() || "ACCEPTED".equals(f.state())) return new Decision(true,true,"");
        if (("PENDING".equals(f.state()) || "DECLINED".equals(f.state()))
                && f.initiator()!=null && f.initiator()!=f.actor()) return new Decision(true,true,"回复将接受此消息请求");
        if ("NONE".equals(f.state()) && f.allowRequests()) return new Decision(true,false,"可发送一条不超过300字的文字招呼");
        return new Decision(false,false,"PENDING".equals(f.state())?"等待对方接受消息请求":"暂时无法向该用户发送消息");
    }
}
