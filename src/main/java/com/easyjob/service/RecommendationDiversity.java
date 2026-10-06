package com.easyjob.service;

import com.easyjob.vo.ArticleListVO;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Reorder within a page and a readable segment; never add, drop or expose articles. */
public final class RecommendationDiversity {
    private RecommendationDiversity() {}
    public static List<ArticleListVO> reorder(List<ArticleListVO> ranked) {
        var remaining=new ArrayList<>(ranked);
        var result=new ArrayList<ArticleListVO>(ranked.size());
        while(!remaining.isEmpty()) {
            int choice=0;
            if(result.size()>=2) {
                var last=result.getLast();var previous=result.get(result.size()-2);
                boolean authorRun=last.getUserId()!=null && Objects.equals(last.getUserId(),previous.getUserId());
                boolean categoryRun=last.getCategoryId()!=null && Objects.equals(last.getCategoryId(),previous.getCategoryId());
                // At most five ranked positions: relevance remains the dominant signal.
                int bestPenalty=4;
                for(int i=0;i<Math.min(5,remaining.size());i++) {
                    var candidate=remaining.get(i);
                    if(!Objects.equals(candidate.getReadableNow(),remaining.getFirst().getReadableNow()))break;
                    int penalty=(authorRun && Objects.equals(candidate.getUserId(),last.getUserId())?2:0)
                            +(categoryRun && Objects.equals(candidate.getCategoryId(),last.getCategoryId())?1:0);
                    if(penalty<bestPenalty){choice=i;bestPenalty=penalty;}
                    if(bestPenalty==0)break;
                }
            }
            result.add(remaining.remove(choice));
        }
        return result;
    }
}
