package com.easyjob.controller;
import com.easyjob.service.RecommendationFeedbackService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api/recommendation/feedback") @RequiredArgsConstructor
public class RecommendationFeedbackController {
 private final RecommendationFeedbackService service;
 public record Feedback(String kind) {}
 @GetMapping public ResponseVO<?> list(){return ResponseVO.success(service.list(UserContext.getUserId()));}
 @PutMapping("/{id}") public ResponseVO<?> save(@PathVariable Long id,@RequestBody Feedback body){service.save(UserContext.getUserId(),id,body.kind());return ResponseVO.success("已更新推荐偏好");}
 @DeleteMapping("/{id}") public ResponseVO<?> remove(@PathVariable Long id){service.remove(UserContext.getUserId(),id);return ResponseVO.success("已恢复推荐");}
}
