package com.easyjob.controller;

import com.easyjob.service.SocialService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import com.easyjob.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController @RequestMapping("/api/social") @RequiredArgsConstructor
public class SocialController {
    private final SocialService social;
    public record Follow(boolean following) {}
    public record Block(boolean blocked) {}
    public record Remark(String remark) {}
    public record Privacy(Boolean allowMessageRequests) {}
    public record Preferences(Boolean isTop,Boolean isMuted) {}
    @GetMapping("/relationships") public ResponseVO<?> relationships(@RequestParam List<Long> ids){return ResponseVO.success(social.relationships(UserContext.getUserId(),ids));}
    @GetMapping("/relationships/{target}") public ResponseVO<?> relationship(@PathVariable long target){return ResponseVO.success(social.relationship(UserContext.getUserId(),target));}
    @PutMapping("/relationships/{target}/follow") public ResponseVO<?> follow(@PathVariable long target,@RequestBody Follow value){social.follow(UserContext.getUserId(),target,value.following());return relationship(target);}
    @PutMapping("/relationships/{target}/remark") public ResponseVO<?> remark(@PathVariable long target,@RequestBody Remark value){social.remark(UserContext.getUserId(),target,value.remark());return relationship(target);}
    @PutMapping("/relationships/{target}/block") public ResponseVO<?> block(@PathVariable long target,@RequestBody Block value){social.block(UserContext.getUserId(),target,value.blocked());return relationship(target);}
    @GetMapping("/contacts") public ResponseVO<?> contacts(@RequestParam(defaultValue="friends") String kind,@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="30") int size){return ResponseVO.success(social.contacts(UserContext.getUserId(),kind,q,page,size));}
    @GetMapping("/settings") public ResponseVO<?> settings(){return ResponseVO.success(social.settings(UserContext.getUserId()));}
    @PutMapping("/settings") public ResponseVO<?> settings(@RequestBody Privacy value){if(value.allowMessageRequests()==null)throw new BusinessException(400,"设置值不能为空");social.settings(UserContext.getUserId(),value.allowMessageRequests());return settings();}
    @GetMapping("/summary") public ResponseVO<?> summary(){return ResponseVO.success(social.summary(UserContext.getUserId()));}
    @GetMapping("/requests") public ResponseVO<?> requests(){return ResponseVO.success(social.conversations(UserContext.getUserId(),true));}
    @GetMapping("/conversations/{cid}") public ResponseVO<?> conversation(@PathVariable long cid){return ResponseVO.success(social.conversation(cid,UserContext.getUserId()));}
    @PostMapping("/requests/{cid}/{action}") public ResponseVO<?> handle(@PathVariable long cid,@PathVariable String action){return ResponseVO.success(social.handleRequest(cid,UserContext.getUserId(),action));}
    @PutMapping("/conversations/{cid}/preferences") public ResponseVO<?> preferences(@PathVariable long cid,@RequestBody Preferences value){return ResponseVO.success(social.preferences(cid,UserContext.getUserId(),value.isTop(),value.isMuted()));}
    @GetMapping("/articles/{id}") public ResponseVO<?> article(@PathVariable long id){return ResponseVO.success(social.article(id));}
}
