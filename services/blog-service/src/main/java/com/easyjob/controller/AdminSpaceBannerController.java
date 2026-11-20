package com.easyjob.controller;

import com.easyjob.service.SpaceBannerReviewService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.SpaceBannerSubmission;
import lombok.RequiredArgsConstructor;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/admin/space-banners")
@RequiredArgsConstructor
public class AdminSpaceBannerController {
    private final SpaceBannerReviewService reviews;

    public record Decision(Boolean approved, String reason) {}

    @GetMapping
    public ResponseVO<List<SpaceBannerSubmission>> queue(@RequestParam(defaultValue = "1") int page,
                                                         @RequestParam(defaultValue = "12") int size) {
        return ResponseVO.success(reviews.queue(UserContext.getUserId(), page, size));
    }

    @GetMapping("/{owner}/{id}/image")
    public ResponseEntity<byte[]> preview(@PathVariable Long owner, @PathVariable UUID id) {
        return previewResponse(reviews.reviewerPreview(UserContext.getUserId(), owner, id));
    }

    @PostMapping("/{owner}/{id}")
    public ResponseVO<?> decide(@PathVariable Long owner, @PathVariable UUID id, @RequestBody Decision decision) {
        reviews.decide(UserContext.getUserId(), owner, id, decision.approved(), decision.reason());
        return ResponseVO.success("审核已提交");
    }

    static ResponseEntity<byte[]> previewResponse(byte[] image) {
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("image/webp"))
                .cacheControl(CacheControl.noStore()).body(image);
    }
}
