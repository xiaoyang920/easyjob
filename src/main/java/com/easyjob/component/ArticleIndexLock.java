package com.easyjob.component;

import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleIndexLockMapper;
import lombok.RequiredArgsConstructor;
import org.apache.ibatis.session.SqlSessionFactory;
import org.springframework.stereotype.Component;

/** Holds one MyBatis session/connection for both advisory-lock operations. */
@Component
@RequiredArgsConstructor
public class ArticleIndexLock {
    private final SqlSessionFactory sessions;

    public void withLock(Long articleId, Runnable work) {
        if (articleId == null || articleId <= 0) throw new BusinessException("无效文章id");
        String name = "easyjob_rag_" + articleId;
        try (var session = sessions.openSession(true)) {
            var locks = session.getMapper(ArticleIndexLockMapper.class);
            if (!Integer.valueOf(1).equals(locks.acquire(name)))
                throw new BusinessException("文章索引正在执行，请重试");
            Throwable failure = null;
            try {
                work.run();
            } catch (RuntimeException | Error error) {
                failure = error;
                throw error;
            } finally {
                try {
                    if (!Integer.valueOf(1).equals(locks.release(name)))
                        throw new IllegalStateException("Article index lock could not be released");
                } catch (RuntimeException | Error releaseError) {
                    if (failure != null) failure.addSuppressed(releaseError);
                    else throw releaseError;
                }
            }
        }
    }
}
