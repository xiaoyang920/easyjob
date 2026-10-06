package com.easyjob.agent.controller;

import com.easyjob.agent.service.AgentService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/memory")
public class MemoryController {
    private final AgentService agent;
    public MemoryController(AgentService agent) { this.agent = agent; }
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ResponseVO<?>> memoryError(ResponseStatusException exception) {
        return ResponseEntity.status(exception.getStatusCode()).body(ResponseVO.error(exception.getStatusCode().value(),
                exception.getReason() == null ? "记忆请求参数无效" : exception.getReason()));
    }

    @GetMapping
    public ResponseVO<?> overview(@RequestParam(required=false) Long before,
                                  @RequestParam(defaultValue="30") int limit,
                                  @RequestParam(defaultValue="all") String kind) {
        if ((before != null && before <= 0) || limit < 1 || limit > 50) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        if (!java.util.Set.of("all", "constraint", "decision", "event").contains(kind)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        return ResponseVO.success(agent.memoryRequest(UserContext.getUserId(), HttpMethod.GET,
                "/memory?limit=" + limit + "&kind=" + kind + (before == null ? "" : "&before=" + before), null));
    }
    @PutMapping("/profile")
    public ResponseVO<?> profile(@RequestBody Map<String,Object> body) {
        return ResponseVO.success(agent.memoryRequest(UserContext.getUserId(), HttpMethod.PUT, "/memory/profile", body));
    }
    @PutMapping("/records/{id}")
    public ResponseVO<?> edit(@PathVariable Long id, @RequestBody Map<String,Object> body) {
        if (id <= 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        return ResponseVO.success(agent.memoryRequest(UserContext.getUserId(), HttpMethod.PUT, "/memory/records/" + id, body));
    }
    @DeleteMapping("/records/{id}")
    public ResponseVO<?> delete(@PathVariable Long id, @RequestParam String version) {
        if (id <= 0 || !version.matches("[a-f0-9]{64}")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        return ResponseVO.success(agent.memoryRequest(UserContext.getUserId(), HttpMethod.DELETE, "/memory/records/" + id + "?version=" + version, null));
    }
}
