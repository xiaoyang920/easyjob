package com.easyjob.growth;
import com.easyjob.mapper.GrowthMapper;

import com.easyjob.config.GlobalExceptionHandler;
import com.easyjob.config.RabbitMqConfig;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ReadingGrowthMapper;
import com.easyjob.security.TrustedGatewayFilter;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.service.ReadingGrowthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rabbitmq.client.Channel;
import org.mybatis.spring.mapper.MapperFactoryBean;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.PlatformTransactionManager;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import org.springframework.web.util.ContentCachingResponseWrapper;

/** Standalone test-only host. Real production growth beans, JDBC, Redis, Rabbit and identity filter.
 * Lives in test classes: no fault gate or test HTTP endpoint is shipped in the product JAR. */
@Configuration(proxyBeanMethods=false)
@Profile("growth-lab")
@EnableAutoConfiguration
@EnableScheduling
@Import({GrowthReservations.class,GrowthMessaging.class,GrowthController.class,
         ReadingGrowthService.class,TrustedGatewayFilter.class,GlobalExceptionHandler.class,RabbitMqConfig.class})
public class GrowthLabApplication {
    public static void main(String[] args){SpringApplication.run(GrowthLabApplication.class,args);}
    @Bean public MapperFactoryBean<GrowthMapper> growthMapper(org.apache.ibatis.session.SqlSessionFactory factory){
        MapperFactoryBean<GrowthMapper> mapper=new MapperFactoryBean<>(GrowthMapper.class);
        mapper.setSqlSessionFactory(factory);return mapper;
    }
    @Bean public MapperFactoryBean<ReadingGrowthMapper> readingMapper(org.apache.ibatis.session.SqlSessionFactory factory){MapperFactoryBean<ReadingGrowthMapper> mapper=new MapperFactoryBean<>(ReadingGrowthMapper.class);mapper.setSqlSessionFactory(factory);return mapper;}
    @Bean public org.springframework.web.filter.OncePerRequestFilter instanceLabel(@Value("${lab.instance}")String name){
        return new org.springframework.web.filter.OncePerRequestFilter(){
            @Override protected void doFilterInternal(jakarta.servlet.http.HttpServletRequest request,jakarta.servlet.http.HttpServletResponse response,jakarta.servlet.FilterChain chain)throws jakarta.servlet.ServletException,java.io.IOException{
                ContentCachingResponseWrapper cached=new org.springframework.web.util.ContentCachingResponseWrapper(response);
                long started=System.nanoTime();cached.setHeader("X-Growth-Lab-Instance",name);
                try{chain.doFilter(request,cached);}
                finally{
                    cached.setHeader("X-Growth-Lab-Dispatch-Ms",Double.toString((System.nanoTime()-started)/1_000_000.0));
                    cached.copyBodyToResponse();
                }
            }
        };
    }
    @Bean public AdminConsoleService labAdmin(JdbcTemplate db){
        // Only the admin facade is replaced, to avoid booting unrelated article/Agent services.
        return new AdminConsoleService(null,null,null,null,null,null){
            @Override public void requireAdmin(Long uid){if(uid==null||db.queryForList("SELECT user_id FROM user_info WHERE user_id=? AND role=2 AND status=1",uid).isEmpty())throw new BusinessException(403,"只有管理员可以访问");}
        };
    }
    @Bean public GrowthService labService(GrowthMapper store,GrowthReservations reservations,ReadingGrowthMapper reading,AdminConsoleService admin,
                                          PlatformTransactionManager manager,@Value("${lab.directory}")String directory){
        return new GrowthService(store,reservations,reading,admin,manager){
            @Override public void materialize(Reservation event){
                boolean existed=store.order(event.reservationId())!=null;
                super.materialize(event); // Real production local transaction has returned/committed.
                Path gate=Path.of(directory,"hold-after-commit");
                try{
                    if(!existed&&Files.exists(gate)&&Files.readString(gate).strip().equals(event.reservationId())){
                        Files.writeString(Path.of(directory,"committed-before-ack"),event.reservationId()+":"+ProcessHandle.current().pid());
                        while(Files.exists(gate))Thread.sleep(50);
                    }
                }catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                catch(java.io.IOException error){throw new IllegalStateException(error);}
            }
        };
    }
    @Bean public GrowthWorkers labWorkers(GrowthMapper store,GrowthReservations reservations,GrowthService service,RabbitTemplate rabbit,ObjectMapper json,
                                         @Value("${lab.directory}")String directory){
        return new GrowthWorkers(store,reservations,service,rabbit,json){
            @Override @RabbitListener(queues=GrowthMessaging.ORDERS,containerFactory="growthListenerFactory")
            public void create(GrowthService.Reservation body,Message message,Channel channel)throws Exception{
                if(Boolean.TRUE.equals(message.getMessageProperties().isRedelivered()))
                    Files.writeString(Path.of(directory,"redeliveries.log"),body.reservationId()+":"+ProcessHandle.current().pid()+"\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);
                super.create(body,message,channel);
            }
        };
    }
}
