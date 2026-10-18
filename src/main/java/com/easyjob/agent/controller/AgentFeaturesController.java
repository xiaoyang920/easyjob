package com.easyjob.agent.controller;

import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController @RequestMapping("/api")
public class AgentFeaturesController {
    private final AgentRpcClient rpc;private final AdminConsoleService admin;
    public AgentFeaturesController(AgentRpcClient rpc,AdminConsoleService admin){this.rpc=rpc;this.admin=admin;}
    @GetMapping("/agent/library") public ResponseVO<?> library(@RequestParam(defaultValue="all") String scope,
        @RequestParam(defaultValue="") String keyword,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){
        return ResponseVO.success(rpc.serviceQuery(UserContext.getUserId(),"conversation_library",scope,keyword,page,size,""));
    }
    public record ConversationEdit(String title,Boolean pinned,Long version){}
    @PatchMapping("/agent/conversations/{id}") public ResponseVO<?> edit(@PathVariable long id,@RequestBody ConversationEdit request){
        var data=new HashMap<String,Object>();data.put("version",request.version());
        if(request.title()!=null)data.put("title",request.title());if(request.pinned()!=null)data.put("pinned",request.pinned());
        return ResponseVO.success(rpc.edit(UserContext.getUserId(),"conversation_edit",Long.toString(id),data));
    }
    public record Feedback(String rating,String reason,String comment){}
    @GetMapping("/agent/runs/{id}/feedback") public ResponseVO<?> feedback(@PathVariable String id){
        return ResponseVO.success(rpc.edit(UserContext.getUserId(),"answer_feedback_get",id,Map.of()));
    }
    @PutMapping("/agent/runs/{id}/feedback") public ResponseVO<?> feedback(@PathVariable String id,@RequestBody Feedback request){
        var data=new HashMap<String,Object>();data.put("rating",request.rating());data.put("reason",request.reason()==null?"":request.reason());data.put("comment",request.comment()==null?"":request.comment());
        return ResponseVO.success(rpc.edit(UserContext.getUserId(),"answer_feedback",id,data));
    }
    @GetMapping("/admin/agent-feedback") public ResponseVO<?> report(@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size,@RequestParam(defaultValue="business")String source){
        Long uid=UserContext.getUserId();admin.requirePermission(uid,"metrics.read");
        return ResponseVO.success(rpc.serviceQuery(uid,"feedback_report","","",page,size,source));
    }
    @GetMapping("/admin/agent-feedback/{id}") public ResponseVO<?> feedbackDetail(@PathVariable String id){
        Long uid=UserContext.getUserId();admin.requirePermission(uid,"feedback.read");
        return ResponseVO.success(rpc.edit(uid,"feedback_detail",id,Map.of()));
    }
    public record FeedbackReview(String state,String note,Long version,String commandId,String generation){}
    @PutMapping("/admin/agent-feedback/{id}/review") public ResponseVO<?> reviewFeedback(@PathVariable String id,@RequestBody FeedbackReview request){
        Long uid=UserContext.getUserId();admin.requirePermission(uid,"feedback.manage");
        var data=new HashMap<String,Object>();data.put("state",request.state());data.put("note",request.note());data.put("version",request.version());data.put("commandId",request.commandId());data.put("generation",request.generation());
        return ResponseVO.success(rpc.edit(uid,"feedback_review",id,data));
    }
}
