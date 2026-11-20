package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.SpaceBannerReviewMapper;
import com.easyjob.mapper.SpaceSkinMapper;
import com.easyjob.vo.SpaceBannerSubmission;
import com.easyjob.vo.SpaceBannerView;
import com.easyjob.vo.SpaceCustomization.Appearance;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class SpaceBannerReviewService {
    private final SpaceBannerReviewMapper reviews;
    private final SpaceSkinMapper spaces;
    private final FileStorageService files;
    private final AdminConsoleService admin;

    public SpaceBannerSubmission current(Long owner) {
        return reviews.current(owner);
    }

    @Transactional
    public SpaceBannerSubmission submit(Long owner, byte[] image) {
        lockOwner(owner);
        reviews.submit(owner, UUID.randomUUID().toString(), image);
        return reviews.current(owner);
    }

    @Transactional
    public SpaceBannerSubmission position(Long owner, UUID reviewId, Integer position) {
        return updateView(owner, reviewId, SpaceCustomizationService.legacyView(position));
    }

    @Transactional
    public SpaceBannerSubmission updateView(Long owner, UUID reviewId, SpaceBannerView view) {
        String encoded = view.encode();
        lockOwner(owner);
        pending(owner, reviewId);
        reviews.position(owner, reviewId.toString(), view.y(), encoded);
        return reviews.current(owner);
    }

    @Transactional
    public void withdraw(Long owner, UUID reviewId) {
        lockOwner(owner);
        if (reviews.withdraw(owner, reviewId.toString()) != 1) throw changed();
    }

    public byte[] ownerPreview(Long owner, UUID reviewId) {
        return pendingImage(owner, reviewId);
    }

    public List<SpaceBannerSubmission> queue(Long operator, int page, int size) {
        admin.requirePermission(operator, "reviews.read");
        if (page < 1 || size < 1 || size > 50) throw new BusinessException("分页参数无效");
        return reviews.pending((long) (page - 1) * size, size);
    }

    public byte[] reviewerPreview(Long operator, Long owner, UUID reviewId) {
        admin.requirePermission(operator, "reviews.read");
        return pendingImage(owner, reviewId);
    }

    @Transactional
    public void decide(Long operator, Long owner, UUID reviewId, Boolean approved, String explanation) {
        admin.requirePermission(operator, "reviews.manage");
        if (approved == null) throw new BusinessException("请选择审核结果");
        String reason = explanation == null ? "" : explanation.strip();
        if (reason.length() > 300 || (!approved && reason.isEmpty())) {
            throw new BusinessException("请填写 1 到 300 字的驳回原因");
        }
        lockOwner(owner);
        SpaceBannerSubmission submission = pending(owner, reviewId);
        if (approved) publish(owner, reviewId, submission.view());
        if (reviews.decide(owner, reviewId.toString(), approved ? "APPROVED" : "REJECTED",
                reason.isEmpty() ? null : reason, operator) != 1) throw changed();
    }

    private void publish(Long owner, UUID reviewId, SpaceBannerView view) {
        Appearance old = spaces.appearance(owner);
        String url = files.publishSpaceBanner(pendingImage(owner, reviewId), owner).get("url");
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCompletion(int status) {
                if (status == STATUS_COMMITTED) files.discardSpaceBanner(old.spaceBannerUrl(), owner);
                if (status == STATUS_ROLLED_BACK) files.discardSpaceBanner(url, owner);
            }
        });
        spaces.saveBanner(owner, url, view.y(), view.encode());
    }

    private void lockOwner(Long owner) {
        if (spaces.lockWallet(owner) == null) throw new BusinessException(403, "账号不可用");
    }

    private SpaceBannerSubmission pending(Long owner, UUID reviewId) {
        SpaceBannerSubmission submission = reviews.current(owner);
        if (submission == null || !"PENDING".equals(submission.state())
                || !reviewId.toString().equals(submission.reviewId())) throw changed();
        return submission;
    }

    private byte[] pendingImage(Long owner, UUID reviewId) {
        SpaceBannerReviewMapper.StoredImage image = reviews.image(owner, reviewId.toString());
        if (image == null) throw new BusinessException(404, "待审核头图已失效");
        return image.content();
    }

    private BusinessException changed() {
        return new BusinessException(409, "头图提交已变化，请刷新后重试");
    }
}
