package com.easyjob.service;

import com.easyjob.dto.CommentQuote;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleCommentAnchorMapper;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleCommentAnchorTests {
    private final ArticleCommentAnchorService service = new ArticleCommentAnchorService(mock(ArticleCommentAnchorMapper.class));
    private CommentQuote quote(String text,int start,String prefix,String suffix) {
        var q = new CommentQuote(); q.setExact(text); q.setStart(start); q.setEnd(start+text.length());
        q.setPrefix(prefix); q.setSuffix(suffix); return q;
    }
    @Test void textMatchesBrowserBlockWhitespaceCodeAndEmojiRules() {
        assertEquals("标题 一段 正文🙂 下一行 if (x) { return 1; }",ArticleCommentAnchorService.articleText(
                "<h2>标题</h2><p>一段 <strong>正文🙂</strong><br>下一行</p><pre><div class='article-code-toolbar'>java 放大查看</div><code>if (x) {\n  return 1;\n}</code></pre>"));
    }
    @Test void validatesLiveTextAndComputesItsOwnContentHashAndContext() {
        var q = quote("选中正文",3,"前文 "," 后文"); q.setContentHash("forged");
        var saved = service.validate(q,"<p>前文 <strong>选中正文</strong> 后文</p>");
        assertEquals("选中正文",saved.getExact()); assertEquals(3,saved.getStart());
        assertTrue(saved.getContentHash().matches("[a-f0-9]{64}")); assertNotEquals("forged",saved.getContentHash());
        assertEquals("前文 ",saved.getPrefix()); assertEquals(" 后文",saved.getSuffix());
    }
    @Test void staleFabricatedAndWrongOccurrenceAreRejected() {
        for(var q:new CommentQuote[]{quote("旧正文",3,"前文 "," 后文"),quote("正文",0,"","") ,quote("正文",3,"错误前文","")})
            assertThrows(BusinessException.class,()->service.validate(q,"<p>前文 正文 后文</p>"));
    }
    @Test void limitsAndUtf16OffsetsAreConsistent() {
        var result=service.validate(quote("目标",52,"",""),"<p>"+"🙂".repeat(26)+"目标"+"🙂".repeat(26)+"</p>");
        assertEquals(52,result.getStart()); assertEquals(48,result.getPrefix().length());
        assertFalse(Character.isLowSurrogate(result.getPrefix().charAt(0)));
        assertFalse(Character.isHighSurrogate(result.getSuffix().charAt(result.getSuffix().length()-1)));
        assertThrows(BusinessException.class,()->service.validate(quote("字".repeat(1001),0,"",""),"字".repeat(1001)));
        assertThrows(BusinessException.class,()->service.validate(quote("正文",-1,"",""),"正文"));
        assertNull(service.validate(null,"普通评论无需引用"));
    }
}
