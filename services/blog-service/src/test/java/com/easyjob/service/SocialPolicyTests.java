package com.easyjob.service;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import com.easyjob.service.SocialPolicy.Decision;

class SocialPolicyTests {
    SocialPolicy.Decision decide(boolean blocked,boolean mutual,String state,Long initiator,long actor,boolean privacy){return SocialPolicy.decide(new SocialPolicy.Facts(true,blocked,mutual,state,initiator,actor,privacy));}
    @Test void strangerCanOnlySendAPlainGreeting(){Decision d=decide(false,false,"NONE",null,7,true);assertTrue(d.canMessage());assertFalse(d.canSendRich());}
    @Test void pendingSenderCannotAppendEvenWhenRequestPrivacyIsOpen(){assertFalse(decide(false,false,"PENDING",7L,7,true).canMessage());}
    @Test void recipientCanAcceptByReplyWithoutAutomaticallyFollowing(){assertTrue(decide(false,false,"PENDING",7L,8,false).canSendRich());}
    @Test void rejectedSenderCannotRestartButRecipientCanInitiate(){assertFalse(decide(false,false,"DECLINED",7L,7,true).canMessage());assertTrue(decide(false,false,"DECLINED",7L,8,true).canSendRich());}
    @Test void acceptedChatSurvivesUnfollowAndPrivacyChanges(){assertTrue(decide(false,false,"ACCEPTED",7L,7,false).canSendRich());}
    @Test void mutualUsersDoNotNeedAnApplication(){assertTrue(decide(false,true,"NONE",null,7,false).canSendRich());}
    @Test void blockAndInactiveAccountOverrideConsent(){assertFalse(decide(true,true,"ACCEPTED",7L,7,true).canMessage());assertFalse(SocialPolicy.decide(new SocialPolicy.Facts(false,false,true,"ACCEPTED",7L,7,true)).canMessage());}
}
