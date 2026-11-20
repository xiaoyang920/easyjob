package com.easyjob.controller;

import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.FileStorageService;
import com.easyjob.service.SpaceCustomizationService;
import com.easyjob.service.SpaceBannerReviewService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.SpaceBannerSubmission;
import com.easyjob.vo.SpaceArtwork;
import com.easyjob.vo.SpaceBannerView;
import com.easyjob.vo.SpaceCustomization.Appearance;
import com.easyjob.vo.SpaceCustomization.Catalog;
import com.easyjob.vo.SpaceCustomization.Purchase;
import com.easyjob.vo.SpaceCustomization.PurchaseOrder;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/user/space-customization")
@RequiredArgsConstructor
@Slf4j
public class SpaceCustomizationController {
    private final SpaceCustomizationService customization;
    private final SpaceBannerReviewService bannerReviews;
    private final FileStorageService files;
    private final RedisComponent redis;

    public record BuyProduct(String productId, UUID requestId, Integer expectedPrice) {}
    public record WearArtwork(String artworkId) {}
    public record BannerPosition(String url, Integer position, SpaceBannerView view) {}
    public record ReviewPosition(Integer position, SpaceBannerView view) {}

    @GetMapping
    public ResponseVO<Catalog> catalog() {
        return ResponseVO.success(customization.catalog(owner()));
    }

    @GetMapping("/orders")
    public ResponseVO<List<PurchaseOrder>> orders() {
        return ResponseVO.success(customization.purchaseOrders(owner()));
    }

    @PostMapping("/purchase")
    public ResponseVO<Purchase> purchase(@RequestBody BuyProduct request) {
        Long owner = owner();
        Purchase purchase = customization.purchase(owner, request.productId(), request.requestId(), request.expectedPrice());
        try {
            redis.deleteUserSpaceVO(owner);
        } catch (RuntimeException error) {
            log.warn("Could not invalidate profile cache after decoration purchase for {}", owner, error);
        }
        return ResponseVO.success(purchase.alreadyOwned() ? "已拥有" : "购买成功", purchase);
    }

    @GetMapping("/stickers")
    public ResponseVO<List<SpaceArtwork>> stickerPacks() {
        return ResponseVO.success(customization.ownedStickerPacks(owner()));
    }

    @PutMapping("/artworks/{slot}")
    public ResponseVO<Appearance> wear(@PathVariable String slot, @RequestBody WearArtwork input) {
        if (input.artworkId() == null) throw new BusinessException("请选择作品");
        return ResponseVO.success(customization.wearArtwork(owner(), slot, input.artworkId()));
    }

    @DeleteMapping("/artworks/{slot}")
    public ResponseVO<Appearance> removeArtwork(@PathVariable String slot) {
        return ResponseVO.success(customization.wearArtwork(owner(), slot, null));
    }

    @PutMapping("/banner-position")
    public ResponseVO<Appearance> updatePosition(@RequestBody BannerPosition request) {
        Long owner = owner();
        return ResponseVO.success(request.view() == null
                ? customization.updatePosition(owner, request.url(), request.position())
                : customization.updateView(owner, request.url(), request.view()));
    }

    @GetMapping("/banner-review")
    public ResponseVO<SpaceBannerSubmission> currentBannerReview() {
        return ResponseVO.success(bannerReviews.current(owner()));
    }

    @GetMapping("/banner-review/{id}/image")
    public ResponseEntity<byte[]> pendingBanner(@PathVariable UUID id) {
        return AdminSpaceBannerController.previewResponse(bannerReviews.ownerPreview(owner(), id));
    }

    @PutMapping("/banner-review/{id}/position")
    public ResponseVO<SpaceBannerSubmission> positionPendingBanner(@PathVariable UUID id, @RequestBody ReviewPosition input) {
        Long owner = owner();
        return ResponseVO.success(input.view() == null ? bannerReviews.position(owner, id, input.position())
                : bannerReviews.updateView(owner, id, input.view()));
    }

    @DeleteMapping("/banner-review/{id}")
    public ResponseVO<?> withdrawPendingBanner(@PathVariable UUID id) {
        bannerReviews.withdraw(owner(), id);
        return ResponseVO.success("已撤回头图审核");
    }

    @DeleteMapping("/banner")
    public ResponseVO<Appearance> removeBanner() {
        Long owner = owner();
        Appearance previous = customization.replaceBanner(owner, null);
        files.discardSpaceBanner(previous.spaceBannerUrl(), owner);
        return ResponseVO.success(previous.withoutBanner());
    }

    private Long owner() {
        Long owner = UserContext.getUserId();
        if (owner == null) throw new BusinessException(401, "请先登录");
        return owner;
    }
}
