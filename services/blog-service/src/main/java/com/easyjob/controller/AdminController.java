package com.easyjob.controller;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController @RequestMapping("/api/admin") @RequiredArgsConstructor
public class AdminController {
    private final AdminConsoleService service;
    private final com.easyjob.service.AdminUserService adminUsers;
    private final com.easyjob.service.ArticleRevisionService revisions;
    private final com.easyjob.service.AdminOperationsService operations;
    @GetMapping("/operations") public ResponseVO<?> operations(){return ResponseVO.success(operations.summary(UserContext.getUserId()));}
    @GetMapping("/operations/jobs") public ResponseVO<?> jobs(@RequestParam(defaultValue="article") String queue,@RequestParam(defaultValue="dead") String state,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(operations.jobs(UserContext.getUserId(),queue,state,page,size));}
    @GetMapping("/operations/runs") public ResponseVO<?> runs(@RequestParam(defaultValue="all") String state,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(operations.runs(UserContext.getUserId(),state,page,size));}
    @PostMapping("/operations/jobs/{queue}/{id}/retry") public ResponseVO<?> retry(@PathVariable String queue,@PathVariable String id){operations.retry(UserContext.getUserId(),queue,id);return ResponseVO.success("已提交重试");}
    public record Reconcile(String kind) {}
    @PostMapping("/operations/reconcile") public ResponseVO<?> reconcile(@RequestBody Reconcile body){operations.reconcile(UserContext.getUserId(),body.kind());return ResponseVO.success("已提交对账");}
    public record Review(String decision,String reason) {}
    @GetMapping("/reviews") public ResponseVO<?> reviews(@RequestParam(defaultValue="1") Integer state,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(revisions.queue(UserContext.getUserId(),state,page,size));}
    @GetMapping("/reviews/{id}") public ResponseVO<?> reviewDetail(@PathVariable Long id){return ResponseVO.success(revisions.reviewDetail(UserContext.getUserId(),id));}
    @PostMapping("/reviews/{id}") public ResponseVO<?> review(@PathVariable Long id,@RequestBody Review body){revisions.review(UserContext.getUserId(),id,body.decision(),body.reason());return ResponseVO.success("审核已提交");}
    public record Level(Integer expectedLevel,Integer level) {}
    public record Visibility(Integer expectedStatus,Integer status) {}
    @GetMapping("/me") public ResponseVO<?> me(){return ResponseVO.success(service.me(UserContext.getUserId()));}
    @GetMapping("/overview") public ResponseVO<?> overview(){return ResponseVO.success(service.overview(UserContext.getUserId()));}
    @GetMapping("/articles") public ResponseVO<?> articles(@RequestParam(defaultValue="") String keyword,@RequestParam(required=false) Integer status,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(service.articles(UserContext.getUserId(),keyword,status,page,size));}
    @GetMapping("/users") public ResponseVO<?> users(@RequestParam(defaultValue="") String keyword,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(service.users(UserContext.getUserId(),keyword,page,size));}
    @GetMapping("/users/{id}") public ResponseVO<?> userDetail(@PathVariable Long id){return ResponseVO.success(adminUsers.detail(UserContext.getUserId(),id));}
    @PutMapping("/users/{id}") public ResponseVO<?> updateUser(@PathVariable Long id,@RequestBody com.easyjob.service.AdminUserService.Update body){adminUsers.update(UserContext.getUserId(),id,body);return ResponseVO.success("用户资料已更新");}
    @GetMapping("/logs") public ResponseVO<?> logs(@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){return ResponseVO.success(service.logs(UserContext.getUserId(),page,size));}
    @PutMapping("/articles/{id}/reading-level") public ResponseVO<?> level(@PathVariable Long id,@RequestBody Level body){service.level(UserContext.getUserId(),id,body.expectedLevel(),body.level());return ResponseVO.success("等级已保存");}
    @PutMapping("/articles/{id}/visibility") public ResponseVO<?> visibility(@PathVariable Long id,@RequestBody Visibility body){service.visibility(UserContext.getUserId(),id,body.expectedStatus(),body.status());return ResponseVO.success("文章状态已更新");}
}
