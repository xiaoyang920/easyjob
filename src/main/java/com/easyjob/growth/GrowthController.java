package com.easyjob.growth;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import org.springframework.web.bind.annotation.*;
import java.util.UUID;

@RestController @RequestMapping("/api/growth")
public class GrowthController {
    final GrowthService service;
    public GrowthController(GrowthService service){this.service=service;}
    public record Grab(UUID requestId){}
    @GetMapping("/activities") public ResponseVO<?> activities(){return ResponseVO.success(service.activities());}
    @PostMapping("/activities/{id}/reservations") public ResponseVO<?> grab(@PathVariable UUID id,@RequestBody Grab body){
        if(body.requestId()==null)throw new com.easyjob.exception.BusinessException(400,"缺少请求编号");
        return ResponseVO.success(service.grab(UserContext.getUserId(),id.toString(),body.requestId().toString()));
    }
    @GetMapping("/activities/{aid}/reservations/{id}") public ResponseVO<?> result(@PathVariable UUID aid,@PathVariable UUID id){return ResponseVO.success(service.result(UserContext.getUserId(),aid.toString(),id.toString()));}
    @GetMapping("/orders") public ResponseVO<?> orders(){return ResponseVO.success(service.orders(UserContext.getUserId()));}
    @PostMapping("/orders/{id}/pay") public ResponseVO<?> pay(@PathVariable UUID id){return ResponseVO.success(service.pay(UserContext.getUserId(),id.toString()));}
    @GetMapping("/wallet") public ResponseVO<?> wallet(){return ResponseVO.success(service.wallet(UserContext.getUserId()));}
    @GetMapping("/admin/activities") public ResponseVO<?> adminList(){return ResponseVO.success(service.adminActivities(UserContext.getUserId()));}
    @PostMapping("/admin/activities") public ResponseVO<?> create(@RequestBody GrowthService.Create body){return ResponseVO.success(service.create(UserContext.getUserId(),body));}
    @PostMapping("/admin/activities/{id}/activate") public ResponseVO<?> activate(@PathVariable UUID id){return ResponseVO.success(service.activate(UserContext.getUserId(),id.toString()));}
    @GetMapping("/admin/activities/{id}/audit") public ResponseVO<?> audit(@PathVariable UUID id){return ResponseVO.success(service.audit(UserContext.getUserId(),id.toString()));}
    @PostMapping("/admin/activities/{id}/pause") public ResponseVO<?> pause(@PathVariable UUID id){service.pause(UserContext.getUserId(),id.toString());return ResponseVO.success("活动已暂停");}
    @PostMapping("/admin/activities/{id}/resume") public ResponseVO<?> resume(@PathVariable UUID id){service.resumeActivity(UserContext.getUserId(),id.toString());return ResponseVO.success("活动已恢复");}
    @PostMapping("/admin/activities/{aid}/reservations/{id}/retry") public ResponseVO<?> retry(@PathVariable UUID aid,@PathVariable UUID id){return ResponseVO.success(service.retryReservation(UserContext.getUserId(),aid.toString(),id.toString()));}
}
